"""Base Pydantic configuration for WorkRecorder public contracts."""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Strict base model for typed cross-boundary contracts.

    Attributes:
        model_config: Pydantic configuration that rejects unknown fields,
            validates assignments, and serializes enum values predictably.
    """

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", validate_assignment=True, use_enum_values=False)
