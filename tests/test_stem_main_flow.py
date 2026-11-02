from types import SimpleNamespace

from lastrada import pipeline
from lastrada.config import Settings, load_settings
from lastrada.schemas.models import Interval


def _comparison(
    *,
    accepted=True,
    source_stem="guitar",
    derivative_stem="guitar",
    mean_dtw_cost=None,
    duration_ratio=None,
):
    evidence = SimpleNamespace(
        accepted=accepted,
        source_stem=source_stem,
        derivative_stem=derivative_stem,
        refined_new_start=12.25,
        refined_new_end=17.75,
        same_label=source_stem == derivative_stem,
        reason=(
            "alignment passed guardrails"
            if accepted
            else "no alignment passed overlap and duration guardrails"
        ),
        mean_dtw_cost=(0.22 if accepted else mean_dtw_cost),
        pitch_shift_semitones=0 if accepted else None,
        duration_ratio=(1.04 if accepted else duration_ratio),
    )
    return SimpleNamespace(evidence=[evidence])


def _candidate(index=0, source="sampleid_rank_sequence"):
    return Interval(
        new_start=10.0 + index,
        new_end=20.0 + index,
        original_start=30.0 + index,
        original_end=40.0 + index,
        source=source,
        status="candidate",
        similarity=0.91,
    )


def test_stem_assistance_refines_a_coarse_sony_candidate(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "compare_candidate_stems",
        lambda *_args, **_kwargs: _comparison(),
    )
    candidate = _candidate()

    updated, comparisons = pipeline.stem_assist_candidates(
        object(),
        object(),
        [candidate],
        object(),
        Settings(stem_enabled=True),
    )

    assert len(comparisons) == 1
    assert updated[0].new_start == 12.25
    assert updated[0].new_end == 17.75
    assert updated[0].original_start == 30.0
    assert updated[0].source == "stem-assisted DTW · guitar → guitar"


def test_stem_assistance_does_not_replace_existing_full_mix_dtw(monkeypatch):
    monkeypatch.setattr(
        pipeline,
        "compare_candidate_stems",
        lambda *_args, **_kwargs: _comparison(),
    )
    candidate = _candidate(source="dtw_chroma_local_alignment")
    candidate = candidate.model_copy(update={"new_start": 11.0, "new_end": 18.0})

    updated, _ = pipeline.stem_assist_candidates(
        object(),
        object(),
        [candidate],
        object(),
        Settings(stem_enabled=True),
    )

    assert updated[0] == candidate


def test_explicit_lab_setting_can_evaluate_all_candidates(monkeypatch):
    calls = []

    def fake_compare(*_args, **_kwargs):
        calls.append(1)
        return _comparison(accepted=False)

    monkeypatch.setattr(pipeline, "compare_candidate_stems", fake_compare)
    candidates = [_candidate(index) for index in range(50)]

    updated, comparisons = pipeline.stem_assist_candidates(
        object(),
        object(),
        candidates,
        object(),
        Settings(stem_enabled=True, stem_max_candidates=50),
    )

    assert len(updated) == 50
    assert len(comparisons) == 50
    assert len(calls) == 50


def test_default_dtw_guardrails_allow_point_one_to_ten_x():
    settings = Settings()

    assert settings.dtw_min_duration_ratio == 0.1
    assert settings.dtw_max_duration_ratio == 10.0
    assert settings.stem_max_candidates == 1
    assert settings.stem_model_name == "htdemucs"
    assert settings.stem_probe_seconds == 8.0


def test_stem_settings_can_be_enabled_from_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("LASTRADA_STEM_ENABLED", "1")
    monkeypatch.setenv("LASTRADA_STEM_MODEL", "htdemucs")
    monkeypatch.setenv("LASTRADA_STEM_MAX_CANDIDATES", "2")
    monkeypatch.setenv("LASTRADA_STEM_PADDING_SECONDS", "6.5")
    monkeypatch.setenv("LASTRADA_STEM_CROSS_OTHER", "0")

    settings = load_settings(tmp_path / "missing.json")

    assert settings.stem_enabled is True
    assert settings.stem_model_name == "htdemucs"
    assert settings.stem_max_candidates == 2
    assert settings.stem_separation_padding_seconds == 6.5
    assert settings.stem_include_cross_other is False


def test_stem_evidence_records_match_reviewer_table_verdicts():
    comparisons = [
        _comparison(),
        _comparison(source_stem="guitar", derivative_stem="other"),
        _comparison(accepted=False, source_stem="vocals", derivative_stem="vocals"),
        _comparison(
            accepted=False,
            source_stem="drums",
            derivative_stem="drums",
            mean_dtw_cost=0.72,
            duration_ratio=1.18,
        ),
    ]

    records = pipeline._stem_evidence_records(comparisons)

    assert [record.dtw_result for record in records] == [
        "accepted",
        "accepted",
        "rejected",
        "weak",
    ]
    assert records[0].interpretation == "strong supporting evidence"
    assert records[1].interpretation == "possible separator spillover"
    assert records[2].interpretation == "no supporting vocal alignment"
    assert records[3].interpretation == "no useful alignment"
    assert records[0].duration_ratio == 1.04


def test_recording_evidence_is_not_gated_by_master_scope():
    publishing_only = SimpleNamespace(analysis_scope=["publishing"])

    assert pipeline._should_run_recording_evidence(
        publishing_only, object(), Settings(stem_enabled=False)
    )
    assert pipeline._should_run_recording_evidence(
        publishing_only, None, Settings(stem_enabled=True)
    )
    assert not pipeline._should_run_recording_evidence(
        publishing_only, None, Settings(stem_enabled=False)
    )


def test_on_demand_probe_bounds_one_best_pair_and_preserves_review(monkeypatch):
    from lastrada.schemas.models import Analysis, Intake, Work

    intake = Intake(
        case_id="probe",
        original_work=Work(title="Original", artist="Test"),
        new_work=Work(title="New", artist="Test"),
        analysis_scope=["master"],
    )
    result = Analysis(case_id="probe", input=intake)
    candidates = [
        Interval(
            new_start=0,
            new_end=150,
            original_start=0,
            original_end=200,
            source="sampleid",
            similarity=0.5,
        ),
        Interval(
            new_start=150,
            new_end=300,
            original_start=200,
            original_end=400,
            source="sampleid",
            similarity=0.9,
        ),
    ]
    result.master.locate.sample_occurrences = candidates
    before = result.model_dump()
    calls = []

    def run(updated, original, new, probes, settings):
        calls.append((probes, settings))
        updated.methods["stems"] = "test evidence"
        return probes

    monkeypatch.setattr(pipeline, "_run_optional_stem_assistance", run)
    updated = pipeline.run_stem_probe(result, object(), object(), Settings())
    probes, settings = calls[0]
    assert len(probes) == 1
    assert probes[0].new_start >= 150
    assert probes[0].new_end - probes[0].new_start <= 8
    assert probes[0].original_end - probes[0].original_start <= 8
    assert settings.stem_model_name == "htdemucs"
    assert settings.stem_max_candidates == 1
    assert settings.stem_separation_padding_seconds == 1
    assert settings.stem_include_cross_other is False
    assert updated.master.model_dump() == result.master.model_dump()
    assert result.model_dump() == before


def test_probe_never_invents_source_positions():
    assert pipeline.short_stem_candidate([Interval(new_start=0, new_end=8, source="pfnmf")]) is None


def test_default_stem_budget_is_one_comparison_not_fifty(monkeypatch):
    from unittest.mock import Mock

    compare = Mock(return_value=_comparison(accepted=False))
    monkeypatch.setattr(pipeline, "compare_candidate_stems", compare)
    candidates = [_candidate(i) for i in range(50)]
    updated, results = pipeline.stem_assist_candidates(
        object(), object(), candidates, object(), Settings(stem_enabled=True)
    )
    assert compare.call_count == 1
    assert len(results) == 1 and len(updated) == 50
