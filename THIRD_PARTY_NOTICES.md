# Third-Party Notices

The VeriGym wheel contains no external benchmark corpus, simulator, synthesis
binary, Docker image, PDK, commercial tool, model weight, or model service.
Those components are user-supplied and retain their upstream licenses.

Runtime Python dependencies are installed separately and are not copied into
the VeriGym wheel. Their authoritative license texts are provided by their own
distributions. The dependency metadata audited for this release candidate
identifies PyYAML and Rich as MIT-licensed; Pydantic and Typer publish their
license metadata and texts in their respective distributions.

`tests/fixtures/verilog_eval_v2_synthetic` is a first-party synthetic fixture,
not VerilogEval data. Its committed `LICENSE` grants the MIT License.

The optional Icarus Verilog and Yosys integrations execute separately installed
or containerized upstream tools. VeriGym does not redistribute those binaries.
