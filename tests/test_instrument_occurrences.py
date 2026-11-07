from types import SimpleNamespace

from lastrada.config import Settings
from lastrada.schemas.models import Analysis, Intake, Work, Interval, StemEvidence
from lastrada.separation import occurrences as instruments


def sample():
    intake = Intake(
        case_id="test",
        original_work=Work(title="Source", artist="Test"),
        new_work=Work(title="Mix", artist="Test"),
        analysis_scope=["master"],
    )
    result = Analysis(
        case_id="test",
        input=intake,
        durations={"new": 40, "original": 40},
    )
    result.master.locate.sample_occurrences = [
        Interval(
            new_start=0,
            new_end=4,
            original_start=0,
            original_end=4,
            source="sampleid",
            similarity=0.6,
        ),
        Interval(
            new_start=20,
            new_end=24,
            original_start=0,
            original_end=4,
            source="sampleid",
            similarity=0.9,
        ),
        # Overlapping detector window for the same derivative occurrence.
        Interval(
            new_start=20.2,
            new_end=24.2,
            original_start=0,
            original_end=4,
            source="sampleid",
            similarity=0.4,
        ),
        Interval(
            new_start=10,
            new_end=14,
            original_start=5,
            original_end=9,
            source="sampleid",
            similarity=0.8,
        ),
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


def test_relationship_groups_collapse_duplicates_and_choose_best_representative():
    groups = instruments.relationship_groups(sample())

    assert len(groups) == 3
    repeated = groups[0]
    assert len(repeated.occurrences) == 2
    assert repeated.representative.new_start == 20
    assert repeated.representative.similarity == 0.9
    assert "highest Sony similarity" in repeated.representative_selection

    rows = instruments.occurrence_rows(sample())
    assert len(rows) == 3
    assert rows[0].interval.new_start == 20
    assert rows[0].status == "pending"
    assert "2 grouped use(s)" in rows[0].reason
    assert rows[2].status == "no_source"


def test_one_representative_per_group_and_resumes_without_reprocessing(monkeypatch):
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
                evidence("bass" if probe.new_start >= 20 else "drums"),
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
        on_progress=lambda value: saves.append(value.model_dump()),
    )
    assert calls == [20]
    assert [row.status for row in first.instrument_occurrences] == [
        "checked",
        "failed",
        "no_source",
    ]
    assert first.instrument_occurrences[0].suggested_instruments == ["Bass"]
    assert "2 grouped use(s)" in first.instrument_occurrences[0].reason
    assert instruments.instrument_check_complete(first)

    # A full integrated run checks each eligible group once.
    complete = instruments.run_occurrence_instruments(
        result,
        None,
        None,
        Settings(),
        separator=SimpleNamespace(),
        on_progress=lambda value: saves.append(value.model_dump()),
    )
    assert calls == [20, 20, 10]
    assert complete.instrument_occurrences[0].suggested_instruments == ["Bass"]
    assert complete.instrument_occurrences[1].suggested_instruments == ["Drums"]
    assert instruments.instrument_prefill(complete)["element"] == "Bass, Drums"
    assert "role" not in instruments.instrument_prefill(complete)
    assert "lyrics" not in instruments.instrument_prefill(complete)
    assert complete.master == result.master and complete.review == result.review
    assert result.model_dump() == original
    assert len(saves) >= 2

    instruments.run_occurrence_instruments(
        complete,
        None,
        None,
        Settings(),
        separator=SimpleNamespace(),
    )
    assert calls == [20, 20, 10]


def test_legacy_single_probe_can_seed_matching_group_but_not_other_groups():
    result = sample()
    first_interval = result.master.locate.sample_occurrences[1]
    legacy = instruments.InstrumentOccurrence(
        occurrence_id=instruments.occurrence_id(first_interval),
        candidate_number=1,
        interval=first_interval,
        status="checked",
        suggested_instruments=["Bass"],
        evidence=[
            StemEvidence(
                candidate_number=1,
                source_stem="bass",
                new_song_stem="bass",
                dtw_result="accepted",
                interpretation="legacy",
                reason="one probe",
            )
        ],
    )
    result.instrument_occurrences = [legacy]

    rows = instruments.occurrence_rows(result)
    assert rows[0].status == "checked"
    assert rows[0].suggested_instruments == ["Bass"]
    assert rows[1].status == "pending"
    assert instruments.instrument_prefill(result)["element"] == "Bass"
    assert not instruments.instrument_check_complete(result)


def test_download_failure_is_saved_once_and_finalizes_remaining_groups(monkeypatch):
    calls = []

    def fail(*args, **kwargs):
        calls.append(True)
        raise instruments.StemSeparationUnavailable("model unavailable")

    monkeypatch.setattr(instruments, "compare_candidate_stems", fail)
    updated = instruments.run_occurrence_instruments(
        sample(),
        None,
        None,
        Settings(),
        separator=SimpleNamespace(),
    )
    assert len(calls) == 1
    assert updated.instrument_occurrences[0].status == "failed"
    assert updated.instrument_occurrences[1].status == "failed"
    assert updated.instrument_occurrences[2].status == "no_source"
    assert instruments.instrument_check_complete(updated)
    assert instruments.instrument_prefill(updated) == {}


def test_zero_budget_does_not_load_demucs_and_returns_terminal_group_rows(monkeypatch):
    def fail(**kwargs):
        raise AssertionError("must not load model")

    monkeypatch.setattr(instruments, "DemucsSeparator", fail)
    result = instruments.run_occurrence_instruments(
        sample(),
        None,
        None,
        Settings(),
        budget_seconds=0,
    )
    assert [row.status for row in result.instrument_occurrences] == [
        "failed",
        "failed",
        "no_source",
    ]
    assert instruments.instrument_check_complete(result)
    progress = instruments.instrument_progress(result)
    assert progress["total"] == 3
    assert progress["represented_uses"] == 4
