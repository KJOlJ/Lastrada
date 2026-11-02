import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field

from lastrada.schemas.models import StrictModel


class Settings(StrictModel):
    sample_rate: int = Field(default=8000, ge=8000, le=8000)
    reference_components: int = Field(default=8, ge=1, le=32)
    free_components: int = Field(default=8, ge=1, le=32)
    iterations: int = Field(default=80, ge=10, le=500)
    activation_threshold: float = Field(default=0.55, gt=0, lt=1)
    minimum_interval_seconds: float = Field(default=0.25, gt=0, le=10)
    max_duration_seconds: int = Field(default=600, ge=1, le=600)
    sampleid_chunk_seconds: float = Field(default=5.0, ge=1.0, le=10.0)
    sampleid_hop_seconds: float = Field(default=1.0, ge=0.5, le=5.0)
    # Rank + temporal consistency is the primary rule. -1 disables an absolute
    # cosine floor while keeping the field for backwards-compatible configs.
    sampleid_similarity_threshold: float = Field(default=-1.0, ge=-1, le=1)
    sampleid_batch_size: int = Field(default=4, ge=1, le=16)

    # Optional DTW refinement applied only after SampleID proposes a candidate.
    # The 0.1x-10x range is intentionally permissive for exploratory testing and
    # materially increases the chance of false alignments, so every result still
    # requires listening review.
    dtw_enabled: bool = True
    dtw_search_padding_seconds: float = Field(default=4.0, ge=0.0, le=30.0)
    dtw_max_pitch_shift_semitones: int = Field(default=6, ge=0, le=12)
    dtw_min_duration_ratio: float = Field(default=0.1, gt=0, le=1.0)
    dtw_max_duration_ratio: float = Field(default=10.0, ge=1.0, le=10.0)
    dtw_minimum_duration_seconds: float = Field(default=0.5, gt=0, le=10.0)

    # Opt-in candidate validation. Main UI uses one bounded probe after analysis;
    # explicit laboratory configurations may still request more candidates.
    stem_enabled: bool = False
    stem_model_name: Literal["htdemucs_6s", "htdemucs"] = "htdemucs"
    stem_device: Literal["cpu", "cuda"] = "cpu"
    stem_max_candidates: int = Field(default=1, ge=1, le=50)
    stem_separation_padding_seconds: float = Field(default=1.0, ge=1.0, le=12.0)
    stem_include_cross_other: bool = False
    stem_probe_seconds: float = Field(default=8.0, ge=1.0, le=12.0)
    stem_timeout_seconds: int = Field(default=180, ge=30, le=600)


def _optional_bool(name: str) -> bool | None:
    value = os.getenv(name)
    if value is None or not value.strip():
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be one of: 1/0, true/false, yes/no, on/off")


def _environment_overrides() -> dict:
    overrides = {}

    enabled = _optional_bool("LASTRADA_STEM_ENABLED")
    if enabled is not None:
        overrides["stem_enabled"] = enabled

    cross_other = _optional_bool("LASTRADA_STEM_CROSS_OTHER")
    if cross_other is not None:
        overrides["stem_include_cross_other"] = cross_other

    text_fields = {
        "LASTRADA_STEM_MODEL": "stem_model_name",
        "LASTRADA_STEM_DEVICE": "stem_device",
    }
    for environment_name, field_name in text_fields.items():
        value = os.getenv(environment_name)
        if value and value.strip():
            overrides[field_name] = value.strip()

    numeric_fields = {
        "LASTRADA_STEM_MAX_CANDIDATES": ("stem_max_candidates", int),
        "LASTRADA_STEM_PADDING_SECONDS": (
            "stem_separation_padding_seconds",
            float,
        ),
    }
    for environment_name, (field_name, converter) in numeric_fields.items():
        value = os.getenv(environment_name)
        if value and value.strip():
            overrides[field_name] = converter(value.strip())

    return overrides


def load_settings(path="configs/default.json"):
    data = json.loads(Path(path).read_text()) if Path(path).is_file() else {}
    data.update(_environment_overrides())
    return Settings.model_validate(data)
