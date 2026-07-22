# Yosys parser fixtures

`stat_format_compatible_067.json` is a whitespace-normalized semantic capture of
Yosys 0.67 `stat -json` output. It was captured on 2026-07-22 through the committed
`verigym-yosys-area-v1` flow using the good `toy-rtl/counter-basic` candidate and
`toy_cells.lib` SHA-256
`817685fa394822882602ca0469065f0d5db6ee52a07788d16ff8f84ebb536512`.

Capture image identity:

```text
sha256:77aa99d8afc4143f6168f749075a20f387f46d38080f228b7e7ff8e85fcbeaa6
```

The executable reported `Yosys 0.67+post` with git SHA
`b8e7da6f40ae8f552c116bf6c359b07c6533e159`. JSON indentation was normalized
for review; field names and values are the captured output rather than invented
test values. Parser tests separately mutate copies to cover additive fields and
invalid data.
