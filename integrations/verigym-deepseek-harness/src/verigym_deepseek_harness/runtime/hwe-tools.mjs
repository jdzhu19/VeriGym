/** VeriGym's exclusive HWE native-shell v2 tool contribution. */

import fs from 'node:fs'
import net from 'node:net'

export const name = 'verigym-hwe-tools'
export const inject = ['tools']

const SOCKET = process.env.DSH_BROKER_SOCKET
const PROVIDER_MARKER = process.env.DSH_PROVIDER_START_MARKER
const MAX_RESPONSE_BYTES = 2 * 1024 * 1024
const MAX_PROVIDER_CALLS = 64
let providerCalls = 0

if (typeof SOCKET !== 'string' || !SOCKET.startsWith('/broker/')) {
  throw new Error('DSH_BROKER_SOCKET must name the private /broker socket')
}
if (PROVIDER_MARKER !== '/sessions/provider-request-started-v1.json') {
  throw new Error('DSH_PROVIDER_START_MARKER must use the frozen private marker path')
}

function markFirstProviderRequest() {
  fs.writeFileSync(PROVIDER_MARKER, JSON.stringify({
    format_id: 'verigym_deepseek_harness_provider_request_started_v1',
    provider_request_ordinal: 1,
  }), { encoding: 'utf8', flag: 'wx', mode: 0o600 })
}

const objectSchema = (properties, required = []) => ({
  type: 'object',
  properties,
  additionalProperties: false,
  ...(required.length > 0 ? { required } : {}),
})

const brokerResponseSchema = objectSchema({
  ok: { type: 'boolean' },
  text: { type: 'string' },
  sequence: { type: 'integer' },
  workspace_epoch_before: { type: 'integer' },
  workspace_epoch_after: { type: 'integer' },
  changed_paths: { type: 'array', items: { type: 'string' } },
  result_success: { type: 'boolean' },
}, [
  'ok',
  'text',
  'sequence',
  'workspace_epoch_before',
  'workspace_epoch_after',
  'changed_paths',
  'result_success',
])

const tools = [
  {
    name: 'list_files',
    description: 'List a bounded, shallow workspace-relative tree.',
    parameters: objectSchema({ path: { type: 'string', default: '.' } }),
  },
  {
    name: 'read_file',
    description: 'Read a bounded workspace-relative file or line range.',
    parameters: objectSchema({
      path: { type: 'string' },
      start_line: { type: 'integer' },
      end_line: { type: 'integer' },
    }, ['path']),
  },
  {
    name: 'apply_patch',
    description: 'Apply one workspace-relative unified diff.',
    parameters: objectSchema({ patch: { type: 'string' } }, ['patch']),
  },
  {
    name: 'shell',
    description: 'Run one bounded shell command with container-native read access; only workspace changes become the candidate.',
    parameters: objectSchema({
      command: { type: 'string' },
      cwd: { type: 'string' },
    }, ['command']),
  },
  {
    name: 'inspect_diff',
    description: 'Inspect the bounded candidate diff.',
    parameters: objectSchema({}),
  },
  {
    name: 'finish',
    description: 'Finish after validation and diff inspection.',
    parameters: objectSchema({ summary: { type: 'string' } }, ['summary']),
  },
]

function brokerCall(name, args, callId, signal) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection({ path: SOCKET })
    let settled = false
    let bytes = 0
    let data = ''
    const finish = (callback, value) => {
      if (settled) return
      settled = true
      signal.removeEventListener('abort', abort)
      socket.destroy()
      callback(value)
    }
    const abort = () => finish(reject, signal.reason instanceof Error
      ? signal.reason
      : new Error('HWE tool call aborted'))
    signal.addEventListener('abort', abort, { once: true })
    socket.setEncoding('utf8')
    socket.on('connect', () => {
      socket.write(`${JSON.stringify({ id: String(callId), name, arguments: args })}\n`)
    })
    socket.on('data', (chunk) => {
      bytes += Buffer.byteLength(chunk)
      if (bytes > MAX_RESPONSE_BYTES) {
        finish(reject, new Error('HWE broker response exceeded its bound'))
        return
      }
      data += chunk
      if (!data.endsWith('\n')) return
      try {
        const response = JSON.parse(data)
        if (response === null || typeof response !== 'object') {
          throw new Error('HWE broker returned a non-object')
        }
        if (response.ok !== true) {
          throw new Error(typeof response.text === 'string' ? response.text : 'HWE tool rejected')
        }
        finish(resolve, response)
      } catch (error) {
        finish(reject, error)
      }
    })
    socket.on('error', (error) => finish(reject, error))
    socket.on('end', () => {
      if (!settled) finish(reject, new Error('HWE broker closed without a complete response'))
    })
  })
}

export function apply(ctx) {
  ctx.on('agent/request', async (_payload, next) => {
    if (providerCalls >= MAX_PROVIDER_CALLS) {
      throw new Error('VERIGYM_HWE_PROVIDER_CALL_BUDGET_EXHAUSTED')
    }
    providerCalls += 1
    if (providerCalls === 1) markFirstProviderRequest()
    return {
      ...(await next()),
      temperature: 0,
      reasoningEffort: 'off',
      maxTokens: 2048,
    }
  })

  for (const schema of tools) {
    ctx.tools.register({
      ...schema,
      output: {
        schema: brokerResponseSchema,
        render(_args, value) {
          return [{ type: 'text', text: String(value.text) }]
        },
      },
      async execute(args, exec) {
        const response = await brokerCall(schema.name, args, exec.callId, exec.signal)
        if (schema.name === 'finish') exec.concludeTurn()
        return response
      },
    })
  }
}
