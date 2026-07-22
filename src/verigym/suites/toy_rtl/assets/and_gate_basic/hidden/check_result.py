"""Verifier-only marker helper kept outside the agent workspace."""

import sys

text = sys.stdin.read()
raise SystemExit(0 if "VERIGYM_PASS" in text and "VERIGYM_FAIL" not in text else 1)
