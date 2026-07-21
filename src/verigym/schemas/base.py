"""Base model configuration shared by persistent schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    """Forbid misspelled fields and validate assignment consistently."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


SCHEMA_VERSION = "1.0"
PLUGIN_API_VERSION = "1.0"
