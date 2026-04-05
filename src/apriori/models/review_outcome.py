"""ReviewOutcome — a human reviewer's action from the Level 2 audit UI (ERD §3.1.7)."""
from typing import Literal, Optional

from pydantic import BaseModel, model_validator

VALID_ERROR_TYPES = frozenset({
    "description_wrong",
    "relationship_missing",
    "relationship_hallucinated",
    "confidence_miscalibrated",
    "other",
})


class ReviewOutcome(BaseModel):
    """Captures a human reviewer's action from the Level 2 audit UI.

    Conditional validation:
    - ``action == "corrected"`` → ``error_type`` is required and must be a known type.
    - ``action == "verified"`` → ``error_type`` must be absent (None).
    """

    action: Literal["corrected", "verified"]
    error_type: Optional[str] = None

    @model_validator(mode="after")
    def validate_error_type_consistency(self) -> "ReviewOutcome":
        if self.action == "corrected":
            if self.error_type is None:
                raise ValueError("error_type is required when action is 'corrected'")
            if self.error_type not in VALID_ERROR_TYPES:
                raise ValueError(
                    f"error_type '{self.error_type}' is not valid; "
                    f"must be one of {sorted(VALID_ERROR_TYPES)}"
                )
        elif self.action == "verified":
            if self.error_type is not None:
                raise ValueError("error_type must not be set when action is 'verified'")
        return self
