"""Strict analysis boundary: reference answers cannot enter Intake."""

from enum import StrEnum
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Placement(StrEnum):
    THROUGHOUT = "throughout"
    INTRO_CHORUS = "intro_outro_with_chorus"
    CHORUS = "chorus_only"
    INTRO_OUTRO = "intro_outro_without_chorus"
    VERSES = "verses"
    ONE_TIME = "one_time"
    INTRO = "intro_only"
    OUTRO = "outro_only"
    BRIDGE = "bridge_only"
    SELECTED = "selected_sections"


PLACEMENT_CLASSES = [p.value for p in Placement]
Rights = Literal["publishing", "master"]
Status = Literal[
    "unknown", "not_verified", "not_detected", "candidate", "verified", "not_requested"
]


class Work(StrictModel):
    title: str = Field(min_length=1)
    artist: str = Field(min_length=1)
    writers: list[str] = Field(default_factory=list)
    audio_file: str | None = None
    reference_url: str | None = None
    audio_version_warning: str | None = None


class Intake(StrictModel):
    case_id: str = Field(min_length=1, max_length=100)
    original_work: Work
    new_work: Work
    analysis_scope: list[Rights] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_scope(self):
        if len(set(self.analysis_scope)) != len(self.analysis_scope):
            raise ValueError("Rights scope must not contain duplicates")
        return self


class Interval(StrictModel):
    new_start: float = Field(ge=0)
    new_end: float = Field(gt=0)
    original_start: float | None = Field(default=None, ge=0)
    original_end: float | None = Field(default=None, gt=0)
    source: str
    element_id: str | None = None
    status: Literal["estimated", "candidate", "expert_verified"] = "estimated"
    similarity: float | None = Field(default=None, ge=-1, le=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.new_end <= self.new_start:
            raise ValueError("New-work end must be after start")
        if (self.original_start is None) != (self.original_end is None):
            raise ValueError("Source endpoints must both be supplied or both be unknown")
        if self.original_start is not None and self.original_end <= self.original_start:
            raise ValueError("Original end must be after start")
        return self


class Feature(StrictModel):
    feature: str
    element_id: str | None = None
    value: str | float | int | list[str] | None = None
    unit: str | None = None
    source: str
    status: Literal["unknown", "estimated", "candidate", "expert_verified"] = "unknown"
    review_required: bool = True


class StemEvidence(StrictModel):
    candidate_number: int = Field(ge=1)
    source_stem: str = Field(min_length=1)
    new_song_stem: str = Field(min_length=1)
    dtw_result: Literal["accepted", "weak", "rejected"]
    duration_ratio: float | None = Field(default=None, gt=0)
    interpretation: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    mean_dtw_cost: float | None = Field(default=None, ge=0)
    pitch_shift_semitones: int | None = None


class Locate(StrictModel):
    detection_status: Status = "unknown"
    sample_detected: bool | None = None
    # PF-NMF measurements are distinct from candidate recording matches.
    measurement_intervals: list[Interval] = Field(default_factory=list)
    sample_occurrences: list[Interval] = Field(default_factory=list)
    total_covered_seconds: float | None = Field(default=None, ge=0)
    coverage_percentage: float | None = Field(default=None, ge=0, le=100)
    pitch_shift_semitones: float | None = None
    review_required: bool = True

    @model_validator(mode="after")
    def detection_consistency(self):
        if self.detection_status == "verified" and self.sample_detected is not True:
            raise ValueError("Verified reuse must carry sample_detected=true")
        if self.detection_status == "not_detected" and self.sample_occurrences:
            raise ValueError("Not-detected findings cannot contain positive reuse occurrences")
        if self.sample_detected is True and self.detection_status != "verified":
            raise ValueError("Positive reuse claims require expert verification")
        if self.detection_status == "not_detected" and self.sample_detected is not False:
            raise ValueError("not_detected must carry sample_detected=false")
        if (
            self.detection_status in ("unknown", "not_verified", "candidate", "not_requested")
            and self.sample_detected is not None
        ):
            raise ValueError("Unverified states cannot claim sample presence or absence")
        return self


class Description(StrictModel):
    reuse_type: str | None = None
    elements: list[Feature] = Field(default_factory=list)
    sections: list[str] = Field(default_factory=list)
    repetition: str | None = None
    role_in_new_song: str | None = None
    limitations: list[str] = Field(default_factory=list)


class Classification(StrictModel):
    placement: Placement | None = None
    coverage_category: Literal["entire", "more_than_25_percent", "25_percent_or_less"] | None = None
    source: str = "unavailable"
    review_required: bool = True
    reason: str = "Insufficient evidence"


class PathResult(StrictModel):
    rights_type: Rights
    locate: Locate = Field(default_factory=Locate)
    describe: Description = Field(default_factory=Description)
    classification: Classification = Field(default_factory=Classification)


class Narrative(StrictModel):
    text: str = ""
    source: str = "deterministic_template"
    review_required: bool = True


class Review(StrictModel):
    status: Literal["pending", "edited", "approved"] = "pending"
    reviewer: str | None = None
    reviewed_at: str | None = None
    notes: str = ""
    # A complete corrected version; the automated envelope remains immutable.
    corrected: dict | None = None


class Analysis(StrictModel):
    schema_version: str = "0.1.0"
    case_id: str
    input: Intake
    publishing: PathResult = Field(default_factory=lambda: PathResult(rights_type="publishing"))
    master: PathResult = Field(default_factory=lambda: PathResult(rights_type="master"))
    nature_of_use: Narrative = Field(default_factory=Narrative)
    review: Review = Field(default_factory=Review)
    durations: dict[str, float] = Field(default_factory=dict)
    timings_seconds: dict[str, float] = Field(default_factory=dict)
    methods: dict[str, str] = Field(default_factory=dict)
    stem_evidence: list[StemEvidence] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    synthetic: bool = False

    @model_validator(mode="after")
    def consistent_envelope(self):
        if self.case_id != self.input.case_id:
            raise ValueError("Case identifiers must match")
        if self.publishing.rights_type != "publishing" or self.master.rights_type != "master":
            raise ValueError("Rights findings cannot be interchanged")
        return self
