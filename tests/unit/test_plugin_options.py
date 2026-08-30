from __future__ import annotations

import pytest

from verigym.schemas.options import validate_plugin_options


def test_public_token_count_limits_are_not_treated_as_credentials() -> None:
    assert validate_plugin_options(
        {
            "max_context_tokens": 65_536,
            "max_output_tokens": 2_048,
            "max_provider_billed_units": 1_000_000,
        }
    ) == {
        "max_context_tokens": 65_536,
        "max_output_tokens": 2_048,
        "max_provider_billed_units": 1_000_000,
    }


@pytest.mark.parametrize("key", ["token", "access_token", "refresh_token", "max_provider_tokens"])
def test_actual_token_options_remain_rejected(key: str) -> None:
    with pytest.raises(ValueError, match="secret-bearing"):
        validate_plugin_options({key: "not-a-real-secret"})
