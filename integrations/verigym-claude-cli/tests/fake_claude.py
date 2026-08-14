#!/usr/bin/env python3
"""Credential-free fake for Claude CLI process and capability tests."""

import json
import os
import sys
import time

HELP = """
--allowedTools --bare --disable-slash-commands --disallowedTools --effort
--mcp-config --model --name
--no-session-persistence --output-format stream-json --permission-mode dontAsk --print
--strict-mcp-config --tools --verbose --no-chrome --prompt-suggestions
"""


def main() -> None:
    arguments = sys.argv[1:]
    if arguments == ["--version"]:
        print("2.1.168 (Claude Code)")
        return
    if arguments == ["--help"]:
        print(HELP)
        return
    log = os.environ.get("VERIGYM_FAKE_CLAUDE_LOG")
    if log:
        record = {
            "arguments": arguments,
            "anthropic_api_key_present": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "anthropic_auth_token_present": bool(os.environ.get("ANTHROPIC_AUTH_TOKEN")),
            "anthropic_base_url_present": bool(os.environ.get("ANTHROPIC_BASE_URL")),
            "effort": os.environ.get("CLAUDE_CODE_EFFORT_LEVEL"),
            "nonessential_traffic_disabled": os.environ.get(
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"
            ),
            "max_mcp_output_tokens": os.environ.get("MAX_MCP_OUTPUT_TOKENS"),
            "max_output_environment_present": "CLAUDE_CODE_MAX_OUTPUT_TOKENS" in os.environ,
        }
        with open(log, "w", encoding="utf-8") as stream:
            json.dump(record, stream)
    if os.environ.get("VERIGYM_FAKE_CLAUDE_SCENARIO") == "echo-auth":
        credential = os.environ.get("ANTHROPIC_AUTH_TOKEN") or os.environ.get(
            "ANTHROPIC_API_KEY", ""
        )
        print(credential)
        print(credential, file=sys.stderr)
        return
    if os.environ.get("VERIGYM_FAKE_CLAUDE_SCENARIO") == "sleep":
        time.sleep(30)
        return
    allowed = arguments[arguments.index("--allowedTools") + 1].split(",")
    model = arguments[arguments.index("--model") + 1]
    base_model = model[:-4] if model.endswith("[1m]") else model
    events = [
        {
            "type": "system",
            "subtype": "init",
            "model": model,
            "tools": allowed,
        },
        {
            "type": "assistant",
            "message": {
                "model": base_model,
                "content": [{"type": "text", "text": "done"}],
            },
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": 1,
            "result": "done",
            "usage": {
                "input_tokens": 11,
                "output_tokens": 3,
                "cache_creation_input_tokens": 5,
                "cache_read_input_tokens": 7,
            },
            "total_cost_usd": 0.125,
            "modelUsage": {
                base_model: {
                    "inputTokens": 11,
                    "outputTokens": 3,
                    "contextWindow": 1_000_000,
                    "maxOutputTokens": 32_000,
                }
            },
        },
    ]
    for event in events:
        print(json.dumps(event, separators=(",", ":")))


if __name__ == "__main__":
    main()
