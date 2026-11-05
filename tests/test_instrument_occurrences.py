from types import SimpleNamespace
import pytest
from lastrada.config import Settings
from lastrada.schemas.models import Analysis, Intake, Work, Interval, StemEvidence
from lastrada.separation import occurrences as instruments
from lastrada.separation.presence import context_probe


@pytest.mark.parametrize("start,length", [(10, 1.5), (0, 1.5), (10, 4), (10, 10)])
@pytest.mark.parametrize("confirmed", [False, True])
def test_context_probe_keeps_review_metadata_on_the_sample_only(start, length, confirmed):
    cue = {"new_through": start + length + 0.5, "original_through": length + 2.5}
    interval = Interval(
        new_start=start, new_end=start + length, original_start=2, original_end=2 + length,
        source="direct_waveform_local_alignment",
        end_review=None if confirmed else cue,
        ending_review_context=cue if confirmed else None,
    )
    before = interval.model_dump()
    probe = context_probe(interval, 40, 40)
    # Round-trip validation catches invalid model_copy/assignment combinations.
    validated = Interval.model_validate_json(probe.model_dump_json())
    assert validated.end_review is None and validated.ending_review_context is None
    assert validated.new_end - validated.new_start == min(8, max(4, length))
    assert interval.model_dump() == before
    if start == 10 and length == 1.5:
        assert (probe.new_start, probe.new_end) == (8.75, 12.75)
        assert (probe.original_start, probe.original_end) == (0.75, 4.75)


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
        "pending",
        "no_source",
    ]
    assert first.instrument_occurrences[0].suggested_instruments == ["Bass"]
    assert not first.instrument_occurrences[1].suggested_instruments
    assert not instruments.instrument_check_complete(first)
    second = instruments.run_occurrence_instruments(
        first, None, None, Settings(), separator=SimpleNamespace()
    )
    assert calls == [0, 10, 18.5]
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
    assert calls == [0, 10, 18.5]
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
        "pending",
        "no_source",
    ]


def test_old_short_and_checked_results_are_rechecked_under_new_evidence_rules():
    result = sample()
    result.instrument_occurrences = instruments.occurrence_rows(result, "htdemucs_6s")
    for row in result.instrument_occurrences:
        row.evidence_version = 1
        row.status = "too_short"
        row.suggested_instruments = ["Bass"]
    rows = instruments.occurrence_rows(result, "htdemucs_6s")
    assert [r.status for r in rows] == ["pending", "pending", "pending", "no_source"]
    assert all(not r.suggested_instruments for r in rows)
    assert instruments.instrument_prefill(result, "htdemucs_6s") == {}


def test_short_probe_describes_actual_audio_without_claiming_context_is_sampled(monkeypatch):
    import numpy as np
    from lastrada.audio.io import Audio
    from lastrada.separation.presence import describe_region

    result = sample()
    result.master.locate.sample_occurrences = result.master.locate.sample_occurrences[2:3]
    sr = 1000

    def region(stem, offset):
        y = np.ones(6 * sr, dtype=np.float32)
        return SimpleNamespace(
            offset_seconds=offset,
            crop_duration=6,
            candidate_start_local=1,
            candidate_end_local=5,
            stems={
                "full_mix": Audio(y, sr, 6),
                stem: Audio(y, sr, 6),
                "vocals": Audio(y * 0.001, sr, 6),
            },
        )

    source, target = region("bass", 0), region("drums", 17.5)

    def compare(*args, **kwargs):
        return SimpleNamespace(
            evidence=[evidence("bass")], source_region=source, derivative_region=target
        )

    monkeypatch.setattr(instruments, "compare_candidate_stems", compare)
    updated = instruments.run_occurrence_instruments(
        result, None, None, Settings(), separator=SimpleNamespace()
    )
    row = updated.instrument_occurrences[0]
    assert row.context_only and row.status == "checked"
    assert all(e.scope == "context" for e in row.evidence)
    assert row.source_sounds[0].instrument == "Bass"
    assert row.new_sounds[0].instrument == "Drums"
    assert row.new_sounds[0].start == 20 and row.new_sounds[0].end == 21
    assert row.new_sounds[0].scope == "sample"
    assert row.suggested_instruments == [] and instruments.instrument_prefill(updated) == {}
    assert updated.master == result.master
    tiny = describe_region(source, 2, 2.1)
    assert tiny[0].scope == "context" and tiny[0].start == 1 and tiny[0].end == 5
    assert [p.instrument for p in tiny] == ["Bass"]  # Suppress quiet bleed.
    assert tiny == describe_region(source, 2, 2.1)  # Stable repeated source crop.


def test_repeated_source_description_is_shared_but_reuse_decisions_are_independent():
    from lastrada.schemas.models import InstrumentPresence

    rows = instruments.occurrence_rows(sample())[:2]
    for row in rows:
        row.status = "checked"
        row.interval.original_start, row.interval.original_end = 0, 4

    def presence(label):
        return [
            InstrumentPresence(instrument=label, energy_share=0.8, scope="sample", start=0, end=4)
        ]

    rows[0].source_sounds = presence("Bass")
    rows[1].source_sounds = presence("Guitar")
    rows[1].new_sounds = presence("Drums")
    rows[0].suggested_instruments = ["Bass"]
    instruments.stabilize_source_descriptions(rows)
    assert rows[0].source_sounds == rows[1].source_sounds
    assert rows[1].new_sounds[0].instrument == "Drums"
    assert rows[1].suggested_instruments == []
    assert rows[0].source_sounds[0] is not rows[1].source_sounds[0]


def test_resuming_an_earlier_row_preserves_the_saved_source_description():
    from lastrada.schemas.models import InstrumentPresence

    rows = instruments.occurrence_rows(sample())[:2]
    rows[1].interval.original_start, rows[1].interval.original_end = 0, 4
    rows[1].status = "checked"
    rows[1].source_sounds = [
        InstrumentPresence(instrument="Bass", energy_share=0.8, scope="sample", start=0, end=4)
    ]
    canonical = {}
    instruments.stabilize_source_descriptions(rows, canonical)
    rows[0].status = "checked"
    rows[0].source_sounds = [
        InstrumentPresence(instrument="Guitar", energy_share=0.8, scope="sample", start=0, end=4)
    ]
    instruments.stabilize_source_descriptions(rows, canonical)
    assert all(r.source_sounds[0].instrument == "Bass" for r in rows)
