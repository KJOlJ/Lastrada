from types import SimpleNamespace

from fastapi.testclient import TestClient

from lastrada.schemas.models import Analysis, Intake, Work, Interval
from lastrada.separation.occurrences import (
    record_initial_comparisons,
    occurrence_rows,
    instrument_prefill,
    run_occurrence_instruments,
)
from lastrada.web.profile import analysis_settings, PROFILE
from lastrada.web.server import create_app


def example():
    result = Analysis(
        case_id="test",
        input=Intake(
            case_id="test",
            original_work=Work(title="Source", artist="Test"),
            new_work=Work(title="Mix", artist="Test"),
            analysis_scope=["master", "publishing"],
        ),
        durations={"original": 40, "new": 40},
    )
    result.master.locate.sample_occurrences = [
        Interval(
            new_start=0,
            new_end=4,
            original_start=1,
            original_end=5,
            source="sampleid_rank_sequence",
        ),
        Interval(
            new_start=6,
            new_end=10,
            original_start=7,
            original_end=11,
            source="sampleid_rank_sequence",
        ),
    ]
    return result


def evidence(stem, ratio=1, derivative=None):
    return SimpleNamespace(
        source_stem=stem,
        derivative_stem=derivative or stem,
        accepted=True,
        mean_dtw_cost=0.1,
        duration_ratio=ratio,
        same_label=derivative is None,
        pitch_shift_semitones=0,
        reason="generated fixture",
    )


def test_web_profile_preserves_fast_six_stem_top_three_configuration():
    s = analysis_settings()
    assert PROFILE["source_branch"] == "local/stem-fast"
    assert s.stem_enabled and s.stem_model_name == "htdemucs_6s"
    assert s.stem_max_candidates == 3 and s.stem_device == "cpu"
    assert s.stem_include_cross_other and s.stem_separation_padding_seconds == 4
    assert (s.dtw_min_duration_ratio, s.dtw_max_duration_ratio) == (0.5, 2)
    assert s.stem_timeout_seconds <= 180


def test_initial_six_stem_results_link_to_own_refined_times_and_filter_prefills():
    result = example()
    before = [i.model_copy(deep=True) for i in result.master.locate.sample_occurrences]
    result.master.locate.sample_occurrences[1].new_start = 6.5
    comparisons = [
        SimpleNamespace(
            evidence=[
                evidence("full_mix"),
                evidence("guitar"),
                evidence("piano"),
                evidence("bass", ratio=5),
            ]
        ),
        SimpleNamespace(evidence=[evidence("guitar", derivative="other")]),
    ]
    record_initial_comparisons(
        result, before, result.master.locate.sample_occurrences, comparisons, analysis_settings()
    )
    rows = occurrence_rows(result, "htdemucs_6s")
    assert rows[0].suggested_instruments == ["Guitar", "Piano"]
    assert rows[1].suggested_instruments == []
    assert rows[1].interval.new_start == 6.5 and rows[1].probe.new_start == 6
    assert all(row.status == "checked" and row.model_name == "htdemucs_6s" for row in rows)
    assert instrument_prefill(result, "htdemucs_6s")["element"] == "Guitar, Piano"
    assert result.review.corrected is None


def test_four_stem_cache_cannot_impersonate_a_six_stem_check(monkeypatch):
    result = example()
    result.master.locate.sample_occurrences = result.master.locate.sample_occurrences[:1]
    result.instrument_occurrences = occurrence_rows(result, "htdemucs")
    result.instrument_occurrences[0].status = "checked"
    result.instrument_occurrences[0].suggested_instruments = ["Bass"]
    assert instrument_prefill(result, "htdemucs_6s") == {}
    calls = []

    def compare(*args, **kwargs):
        calls.append(True)
        return SimpleNamespace(evidence=[evidence("guitar")])

    monkeypatch.setattr("lastrada.separation.occurrences.compare_candidate_stems", compare)
    updated = run_occurrence_instruments(
        result, None, None, analysis_settings(), separator=SimpleNamespace()
    )
    assert calls == [True]
    assert instrument_prefill(updated, "htdemucs_6s")["element"] == "Guitar"
    run_occurrence_instruments(
        updated, None, None, analysis_settings(), separator=SimpleNamespace()
    )
    assert calls == [True]
    assert result.instrument_occurrences[0].model_name == "htdemucs"


def test_health_exposes_build_identity_without_allowing_unsigned_case_access(monkeypatch):
    monkeypatch.setenv("LASTRADA_BUILD_BRANCH", "local/stem-fast")
    monkeypatch.setenv("LASTRADA_BUILD_SHA", "a" * 40)
    client = TestClient(create_app(mode="api"))
    health = client.get("/health").json()
    assert health["branch"] == "local/stem-fast" and health["commit"] == "a" * 40
    assert health["profile"] == "stem-fast"
    assert client.get("/api/analyses/00000000-0000-0000-0000-000000000001").status_code == 401


def test_existing_fast_local_launcher_still_enables_initial_stem_stage(monkeypatch):
    import os
    from pathlib import Path
    from unittest.mock import patch
    from streamlit.testing.v1 import AppTest
    from lastrada import pipeline

    real_analyze = pipeline.analyze_pair
    observed = []

    def analyze(*args, **kwargs):
        observed.append(kwargs["settings"])
        return real_analyze(*args, **kwargs)

    monkeypatch.setattr(pipeline, "analyze_pair", analyze)
    with patch.dict(os.environ):
        app = AppTest.from_file(
            Path(__file__).resolve().parents[1] / "stem_fast_local_app.py", default_timeout=30
        ).run()
        next(b for b in app.button if b.label == "Start").click().run()
        next(
            c for c in app.checkbox if c.label == "Use Sony SampleID + guarded DTW timing analysis"
        ).uncheck().run()
        next(
            c for c in app.checkbox if c.label == "Use a clearly labeled synthetic demonstration"
        ).check().run()
        next(b for b in app.button if b.label == "Find suggested moments").click().run()
        assert not app.exception
        assert observed and observed[-1].stem_enabled
        assert (
            observed[-1].stem_model_name == "htdemucs_6s" and observed[-1].stem_max_candidates == 3
        )
