from pathlib import Path

import numpy as np

from lastrada.alignment.dtw import DTWRefinementResult
from lastrada.alignment import stems as stem_alignment
from lastrada.alignment.stems import candidate_stem_pairs, compare_candidate_stems
from lastrada.audio.io import Audio
from lastrada.schemas.models import Interval
from lastrada.separation import demucs as demucs_module
from lastrada.separation.demucs import SeparatedRegion


def _audio(seconds=12.0, sample_rate=16000):
    samples = np.zeros(int(seconds * sample_rate), dtype=np.float32)
    return Audio(samples, sample_rate, seconds)


def test_candidate_pairs_prioritize_matching_labels_and_selected_cross_pairs():
    source = {"full_mix", "guitar", "other", "vocals"}
    derivative = {"full_mix", "guitar", "other", "vocals"}
    pairs = candidate_stem_pairs(source, derivative)

    assert pairs[:4] == [
        ("full_mix", "full_mix"),
        ("guitar", "guitar"),
        ("vocals", "vocals"),
        ("other", "other"),
    ]
    assert ("guitar", "other") in pairs
    assert ("other", "guitar") in pairs


def test_demucs_segment_is_normalized_for_integer_only_cli(monkeypatch, tmp_path):
    monkeypatch.setattr(demucs_module, "demucs_available", lambda: True)

    separator = demucs_module.DemucsSeparator(
        cache_dir=tmp_path,
        segment_seconds=7.5,
    )

    assert separator.segment_seconds == 7
    assert isinstance(separator.segment_seconds, int)


def test_stem_comparison_maps_local_alignment_back_to_song_time(monkeypatch, tmp_path):
    original = _audio(30)
    derivative = _audio(80)
    stem_audio = _audio(15)

    class FakeSeparator:
        def separate_region(self, audio, start, end, padding_seconds=4.0):
            offset = 8.0 if audio is original else 48.0
            return SeparatedRegion(
                stems={"guitar": stem_audio, "other": stem_audio},
                offset_seconds=offset,
                candidate_start_local=start - offset,
                candidate_end_local=end - offset,
                crop_duration=15.0,
                model_name="fake",
                cache_path=Path(tmp_path),
            )

    def fake_refine(_source, _target, interval, **_kwargs):
        refined = Interval(
            new_start=2.5,
            new_end=6.5,
            original_start=interval.original_start,
            original_end=interval.original_end,
            source="dtw_chroma_local_alignment",
            status="candidate",
            similarity=interval.similarity,
        )
        return DTWRefinementResult(
            interval=refined,
            accepted=True,
            reason="test",
            mean_cost=0.2,
            pitch_shift_semitones=-2,
            duration_ratio=0.8,
            source_duration=5.0,
            derivative_duration=4.0,
            search_start=0.0,
            search_end=10.0,
            path_points=10,
        )

    monkeypatch.setattr(stem_alignment, "refine_candidate_dtw_details", fake_refine)

    interval = Interval(
        new_start=50.0,
        new_end=55.0,
        original_start=10.0,
        original_end=15.0,
        source="sampleid_chunk_cosine",
        status="candidate",
        similarity=0.95,
    )
    result = compare_candidate_stems(
        original,
        derivative,
        interval,
        FakeSeparator(),
    )

    assert result.best is not None
    assert result.best.source_stem == "guitar"
    assert result.best.derivative_stem == "guitar"
    assert result.best.refined_new_start == 50.5
    assert result.best.refined_new_end == 54.5
    assert result.best.pitch_shift_semitones == -2
    assert result.best.sony_similarity == 0.95
