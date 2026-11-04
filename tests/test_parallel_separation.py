import json
import time
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
import numpy as np
import pytest
import soundfile as sf
from lastrada.audio.io import Audio
from lastrada.schemas.models import Interval
from lastrada.alignment import stems
from lastrada.separation import demucs, occurrences


def test_two_regions_are_separated_concurrently():
    barrier = Barrier(2, timeout=2)

    def separate(audio, start, end, **kwargs):
        barrier.wait()
        return SimpleNamespace(
            offset_seconds=0, candidate_start_local=start, candidate_end_local=end, stems={}
        )

    result = stems.compare_candidate_stems(
        None,
        None,
        Interval(new_start=0, new_end=4, original_start=1, original_end=5, source="generated"),
        SimpleNamespace(separate_region=separate),
        parallel_separation=True,
    )
    assert result.source_region.candidate_start_local == 1
    assert result.derivative_region.candidate_start_local == 0


def test_identical_concurrent_crops_generate_cache_once(monkeypatch, tmp_path):
    monkeypatch.setattr(demucs, "demucs_available", lambda: True)
    separator = demucs.DemucsSeparator(cache_dir=tmp_path)
    calls = []

    def generate(crop, cache_path, start, end):
        calls.append(True)
        time.sleep(0.05)
        cache_path.mkdir()
        sf.write(cache_path / "full_mix.wav", crop.samples, crop.sample_rate)
        (cache_path / "manifest.json").write_text(
            json.dumps(
                {
                    "stems": ["full_mix"],
                    "crop_start": start,
                    "crop_duration": end - start,
                    "model_name": "htdemucs",
                }
            )
        )

    monkeypatch.setattr(separator, "_run_and_cache", generate)
    audio = Audio(np.ones(16000, dtype=np.float32), 16000, 1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(lambda _: separator.separate_region(audio, 0, 1, padding_seconds=0), range(2))
        )
    assert len(calls) == 1
    assert np.array_equal(
        results[0].stems["full_mix"].samples, results[1].stems["full_mix"].samples
    )


@pytest.mark.parametrize(
    "durations,budget,expected_checked,device",
    [([30, 30], 75, 1, "cpu"), ([20, 5, 20], 57, 2, "cpu"), ([30, 30], 75, 1, "cuda")],
)
def test_next_check_waits_for_another_batch_when_budget_is_too_small(
    monkeypatch, durations, budget, expected_checked, device
):
    from lastrada.config import Settings
    from lastrada.schemas.models import Analysis, Intake, Work

    clock = [0.0]
    monkeypatch.setattr(occurrences, "monotonic", lambda: clock[0])
    calls = []

    def compare(*args, **kwargs):
        assert kwargs["parallel_separation"] is (device == "cpu")
        clock[0] += durations[len(calls)]
        calls.append(True)
        return SimpleNamespace(evidence=[])

    monkeypatch.setattr(occurrences, "compare_candidate_stems", compare)
    r = Analysis(
        case_id="generated",
        input=Intake(
            case_id="generated",
            original_work=Work(title="Original", artist="Generated"),
            new_work=Work(title="New", artist="Generated"),
            analysis_scope=["master"],
        ),
        durations={"original": 30, "new": 30},
    )
    r.master.locate.sample_occurrences = [
        Interval(new_start=n, new_end=n + 4, original_start=0, original_end=4, source="generated")
        for n in range(0, len(durations) * 10, 10)
    ]
    updated = occurrences.run_occurrence_instruments(
        r,
        None,
        None,
        Settings(stem_device=device),
        separator=SimpleNamespace(),
        budget_seconds=budget,
    )
    assert len(calls) == expected_checked
    assert [row.status for row in updated.instrument_occurrences] == (
        ["checked"] * expected_checked + ["pending"] * (len(durations) - expected_checked)
    )
