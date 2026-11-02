"""Explicit analysis profile for this branch's Firebase deployment."""

import json
from pathlib import Path

PROFILE = json.loads((Path(__file__).resolve().parents[3] / "configs/web-profile.json").read_text())


def analysis_settings():
    from lastrada.config import Settings

    return Settings(
        stem_enabled=True,
        stem_model_name=PROFILE["stem_model"],
        stem_max_candidates=PROFILE["initial_stem_candidates"],
        stem_separation_padding_seconds=4,
        stem_include_cross_other=True,
    )
