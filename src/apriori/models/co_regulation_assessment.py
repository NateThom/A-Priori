"""CoRegulationAssessment — output of the Level 1.5 co-regulation review (ERD §3.1.6)."""
from pydantic import BaseModel, computed_field


class CoRegulationAssessment(BaseModel):
    """Captures the output of the Level 1.5 co-regulation review.

    Three dimension scores are evaluated against configurable thresholds.
    ``composite_pass`` is True only when every score meets its threshold.
    """

    specificity: float
    structural_corroboration: float
    completeness: float

    # Thresholds are configurable; defaults from ERD §3.1.6.
    specificity_threshold: float = 0.5
    structural_corroboration_threshold: float = 0.3
    completeness_threshold: float = 0.4

    # On failure, actionable guidance for the librarian's next attempt.
    # On pass, may be empty or contain minor notes (ERD §3.1.6).
    feedback: str = ""

    @computed_field
    @property
    def composite_pass(self) -> bool:
        return (
            self.specificity >= self.specificity_threshold
            and self.structural_corroboration >= self.structural_corroboration_threshold
            and self.completeness >= self.completeness_threshold
        )
