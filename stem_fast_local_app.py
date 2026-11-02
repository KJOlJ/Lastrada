"""Fast local entrypoint for Sony SampleID + DTW + Demucs.

The full experimental stem branch can evaluate up to 50 Sony candidates, which
is too slow for an interactive CPU test. This entrypoint keeps stem separation
inside the normal Lastrada website but caps the local run to a small number of
top-ranked Sony candidates.
"""

from pathlib import Path
import os
import runpy


def _bounded_candidate_count() -> int:
    raw = os.getenv("LASTRADA_STEM_FAST_MAX_CANDIDATES", "3")
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(
            "LASTRADA_STEM_FAST_MAX_CANDIDATES must be an integer"
        ) from exc
    return max(1, min(value, 5))


# Force the local interactive profile before app.py loads its settings.
os.environ["LASTRADA_LOCAL_STEM_FAST"] = "1"
os.environ["LASTRADA_STEM_ENABLED"] = "1"
os.environ["LASTRADA_STEM_MODEL"] = os.getenv(
    "LASTRADA_STEM_FAST_MODEL", "htdemucs_6s"
)
os.environ["LASTRADA_STEM_DEVICE"] = os.getenv(
    "LASTRADA_STEM_FAST_DEVICE", "cpu"
)
os.environ["LASTRADA_STEM_MAX_CANDIDATES"] = str(_bounded_candidate_count())
os.environ["LASTRADA_STEM_PADDING_SECONDS"] = os.getenv(
    "LASTRADA_STEM_FAST_PADDING_SECONDS", "4.0"
)
os.environ["LASTRADA_STEM_CROSS_OTHER"] = os.getenv(
    "LASTRADA_STEM_FAST_CROSS_OTHER", "1"
)
os.environ.setdefault("OMP_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

APP = Path(__file__).with_name("app.py")
runpy.run_path(str(APP), run_name="__main__")
