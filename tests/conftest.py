from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def synthetic_source(tmp_path: Path) -> Path:
    root = tmp_path / "verilog-eval"
    dataset = root / "dataset_code-complete-iccad2023"
    dataset.mkdir(parents=True)
    (root / "LICENSE").write_text(
        "MIT License\n\nPermission is hereby granted, free of charge, "
        "to any person obtaining a copy\n",
        encoding="utf-8",
    )
    (root / "VERIGYM_SYNTHETIC_FIXTURE").write_text(
        "Synthetic layout fixture; not benchmark data.\n", encoding="utf-8"
    )
    _write_problem(dataset, "Demo001_and", "&")
    _write_problem(dataset, "Demo002_or", "|")
    return root


def _write_problem(dataset: Path, stem: str, operator: str) -> None:
    interface = "module TopModule(input logic a, input logic b, output logic y);\n"
    prompt = f"Implement this circuit using the {operator} operator.\n\n{interface}"
    reference = (
        "module RefModule(input logic a, input logic b, output logic y);\n"
        f"  assign y = a {operator} b;\n"
        "endmodule\n"
    )
    testbench = """`timescale 1ns/1ps
module tb;
  logic a, b;
  logic y_ref, y_dut;
  integer mismatches = 0;
  RefModule reference(.a(a), .b(b), .y(y_ref));
  TopModule candidate(.a(a), .b(b), .y(y_dut));
  initial begin
    a = 0; b = 0; #1; if (y_ref !== y_dut) mismatches = mismatches + 1;
    a = 0; b = 1; #1; if (y_ref !== y_dut) mismatches = mismatches + 1;
    a = 1; b = 0; #1; if (y_ref !== y_dut) mismatches = mismatches + 1;
    a = 1; b = 1; #1; if (y_ref !== y_dut) mismatches = mismatches + 1;
    $display("Mismatches: %0d in 4 samples", mismatches);
    $finish;
  end
endmodule
"""
    values = {
        "_prompt.txt": prompt,
        "_ifc.txt": interface,
        "_ref.sv": reference,
        "_test.sv": testbench,
    }
    for suffix, content in values.items():
        (dataset / f"{stem}{suffix}").write_text(content, encoding="utf-8")
