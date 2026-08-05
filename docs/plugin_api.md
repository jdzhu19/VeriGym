# Plugin API

Third-party packages import author-facing types from `verigym.plugin_api` and register through
standard entry-point groups:

```toml
[project.entry-points."verigym.suites"]
my-suite = "my_package:MySuite"

[project.entry-points."verigym.tools"]
my-tool = "my_package:MyTool"

[project.entry-points."verigym.agents"]
my-agent = "my_package:MyAgent"
```

Real external-source suites can construct `VeriTask`, `SuiteSourceSnapshot`, verifier-graph,
workspace, interaction, and toolchain-profile contracts entirely from `verigym.plugin_api`.
They must not import `verigym.schemas.*`, `verigym.core.*`, or built-in suite implementation
modules. This keeps plugins on the versioned author-facing surface rather than internal code.

Every descriptor has a stable lowercase ID, package version, provider, and plugin API version.
VeriGym records distribution/version/entry-point origins. One broken or incompatible entry point
is rejected with a bounded diagnostic without disabling unrelated plugins; duplicate IDs remain
an error.

The fixture at [`examples/plugins/conformance/`](../examples/plugins/conformance/) is built and
installed beside the VeriGym wheel. It proves external suite, tool, and agent discovery plus
package-resource loading.

Discovery grants no authority. Core task policy still controls visible tools and paths; the
environment enforces hidden-asset separation, budgets, runtime containment, candidate freezing,
and verifier execution. Artifact parsing never imports or invokes plugins. Plugin code executes
in the host process and is trusted at installation time; use normal Python dependency review and
environment isolation.
