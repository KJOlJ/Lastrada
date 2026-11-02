from types import SimpleNamespace
from lastrada.config import Settings
from lastrada.schemas.models import Analysis, Intake, Work, Interval, StemEvidence
from lastrada.separation import occurrences as instruments


def sample():
    intake = Intake(
        case_id="test",
        original_work=Work(title="Source", artist="Test"),
        new_work=Work(title="Mix", artist="Test"),
        analysis_scope=["master", "publishing"],
    )
    result = Analysis(case_id="test", input=intake, durations={"new": 40, "original": 40})
    result.master.locate.sample_occurrences = [
        Interval(new_start=0, new_end=4, original_start=0, original_end=4, source="sampleid"),
        Interval(new_start=10, new_end=14, original_start=5, original_end=9, source="sampleid"),
        Interval(new_start=20, new_end=21, original_start=0, original_end=4, source="sampleid"),
        Interval(new_start=25, new_end=30, source="pfnmf"),
    ]
    return result


def evidence(stem, accepted=True):
    return SimpleNamespace(
        source_stem=stem,
        derivative_stem=stem,
        accepted=accepted,
        mean_dtw_cost=0.1,
        duration_ratio=1,
        same_label=True,
        pitch_shift_semitones=0,
        reason="test alignment",
    )


def test_each_moment_keeps_own_evidence_and_resumes_without_reprocessing(monkeypatch):
    result = sample()
    original = result.model_dump()
    calls, saves = [], []

    def compare(a, b, probe, separator, **kwargs):
        calls.append(probe.new_start)
        assert kwargs["minimum_duration_ratio"] == 0.5
        assert kwargs["maximum_duration_ratio"] == 2
        assert probe.new_end - probe.new_start <= 8
        return SimpleNamespace(
            evidence=[
                evidence("full_mix"),
                evidence("bass" if probe.new_start < 5 else "drums"),
                evidence("vocals", False),
            ]
        )

    monkeypatch.setattr(instruments, "compare_candidate_stems", compare)
    first = instruments.run_occurrence_instruments(
        result,
        None,
        None,
        Settings(),
        separator=SimpleNamespace(),
        max_new_checks=1,
        on_progress=lambda r: saves.append(r.model_dump()),
    )
    assert [r.status for r in first.instrument_occurrences] == [
        "checked",
        "pending",
        "too_short",
        "no_source",
    ]
    assert first.instrument_occurrences[0].suggested_instruments == ["Bass"]
    assert not first.instrument_occurrences[1].suggested_instruments
    assert not instruments.instrument_check_complete(first)
    second = instruments.run_occurrence_instruments(
        first, None, None, Settings(), separator=SimpleNamespace()
    )
    assert calls == [0, 10]
    assert second.instrument_occurrences[1].suggested_instruments == ["Drums"]
    assert instruments.instrument_check_complete(second)
    assert instruments.instrument_prefill(second)["element"] == "Bass, Drums"
    assert "role" not in instruments.instrument_prefill(second)
    assert "lyrics" not in instruments.instrument_prefill(second)
    assert second.master == result.master and second.review == result.review
    assert result.model_dump() == original
    assert len(saves) >= 2
    instruments.run_occurrence_instruments(
        second, None, None, Settings(), separator=SimpleNamespace()
    )
    assert calls == [0, 10]
    # Edited timing gets a new identity and cannot inherit an instrument label.
    second.master.locate.sample_occurrences[0].new_end = 3
    assert instruments.occurrence_rows(second)[0].status == "pending"
    assert instruments.instrument_prefill(second)["element"] == "Drums"


def test_legacy_single_probe_is_never_applied_to_other_timestamps():
    result = sample()
    result.stem_evidence = [
        StemEvidence(
            candidate_number=1,
            source_stem="bass",
            new_song_stem="bass",
            dtw_result="accepted",
            interpretation="legacy",
            reason="one probe",
        )
    ]
    assert instruments.occurrence_rows(result)[0].status == "pending"
    assert instruments.instrument_prefill(result) == {}
    assert not instruments.instrument_check_complete(result)


def test_download_failure_is_saved_once_and_stops_the_batch(monkeypatch):
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise instruments.StemSeparationUnavailable("model unavailable")

    monkeypatch.setattr(instruments, "compare_candidate_stems", fail)
    updated = instruments.run_occurrence_instruments(
        sample(), None, None, Settings(), separator=SimpleNamespace()
    )
    assert len(calls) == 1
    assert updated.instrument_occurrences[0].status == "failed"
    assert updated.instrument_occurrences[1].status == "pending"
    assert instruments.instrument_prefill(updated) == {}


def test_zero_budget_and_unknown_sources_do_not_load_demucs(monkeypatch):
    def fail(**kwargs):
        raise AssertionError("must not load model")

    monkeypatch.setattr(instruments, "DemucsSeparator", fail)
    result = instruments.run_occurrence_instruments(
        sample(), None, None, Settings(), budget_seconds=0
    )
    assert [r.status for r in result.instrument_occurrences] == [
        "pending",
        "pending",
        "too_short",
        "no_source",
    ]
