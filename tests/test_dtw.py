import numpy as np

from lastrada.alignment.dtw import (
    duration_ratio_is_plausible,
    refine_candidate_dtw,
)
from lastrada.audio.io import Audio
from lastrada.schemas.models import Interval


def _tone(freq, seconds, sr):
    t = np.arange(int(seconds * sr)) / sr
    return 0.7 * np.sin(2 * np.pi * freq * t)


def _phrase(sr=16000):
    # Four distinct harmonic blocks to give DTW a sequence rather than one chord.
    notes = [220.0, 261.63, 329.63, 392.0]
    return np.concatenate([_tone(f, 1.0, sr) for f in notes]).astype(np.float32)


def test_duration_ratio_guardrail():
    assert duration_ratio_is_plausible(10, 7.5, 0.5, 1.5)
    assert duration_ratio_is_plausible(10, 15.0, 0.5, 1.5)
    assert not duration_ratio_is_plausible(10, 0.4, 0.5, 1.5)
    assert not duration_ratio_is_plausible(10, 20.1, 0.5, 1.5)


def test_dtw_refines_inserted_phrase_near_candidate():
    sr = 16000
    phrase = _phrase(sr)
    original_samples = np.concatenate(
        [
            np.zeros(sr, dtype=np.float32),
            phrase,
            np.zeros(sr, dtype=np.float32),
        ]
    )
    new_samples = np.concatenate(
        [
            np.zeros(2 * sr, dtype=np.float32),
            phrase,
            np.zeros(2 * sr, dtype=np.float32),
        ]
    )
    original = Audio(original_samples, sr, len(original_samples) / sr)
    new = Audio(new_samples, sr, len(new_samples) / sr)

    coarse = Interval(
        new_start=1.5,
        new_end=6.5,
        original_start=1.0,
        original_end=5.0,
        source="sampleid_chunk_cosine",
        status="candidate",
        similarity=0.95,
    )

    refined = refine_candidate_dtw(
        original,
        new,
        coarse,
        search_padding=1.0,
        max_pitch_shift_semitones=0,
        minimum_duration_ratio=0.5,
        maximum_duration_ratio=1.5,
    )

    assert refined.source == "dtw_chroma_local_alignment"
    assert abs(refined.new_start - 2.0) < 0.6
    assert abs(refined.new_end - 6.0) < 0.7
    assert refined.similarity == coarse.similarity


def test_dtw_abstains_without_source_timestamps():
    sr = 16000
    y = _phrase(sr)
    audio = Audio(y, sr, len(y) / sr)
    coarse = Interval(
        new_start=0,
        new_end=2,
        source="sampleid_chunk_cosine",
        status="candidate",
        similarity=0.8,
    )
    assert refine_candidate_dtw(audio, audio, coarse) == coarse


def test_dtw_rejects_stationary_and_unrelated_audio_even_with_permissive_ratios():
    from lastrada.alignment.dtw import refine_candidate_dtw_details

    rng = np.random.default_rng(42)
    sr = 16000
    coarse = Interval(new_start=0, new_end=4, original_start=0, original_end=4, source="synthetic")
    for source, target in [
        (_tone(220, 4, sr), _tone(220, 4, sr)),
        (np.zeros(4 * sr), np.zeros(4 * sr)),
        (rng.normal(size=4 * sr), rng.normal(size=4 * sr)),
        (_phrase(), _phrase()[::-1]),
    ]:
        result = refine_candidate_dtw_details(
            Audio(source, sr, 4),
            Audio(target, sr, 4),
            coarse,
            minimum_duration_ratio=0.1,
            maximum_duration_ratio=10,
        )
        assert not result.accepted, result
        assert result.interval == coarse  # Do not manufacture tiny timestamp rows.


def test_dtw_accepts_transposed_and_stretched_phrase():
    from lastrada.alignment.dtw import refine_candidate_dtw_details

    sr = 16000
    source = _phrase()
    target = np.concatenate([_tone(f * 2 ** (3 / 12), 1.3, sr) for f in [220, 261.63, 329.63, 392]])
    coarse = Interval(
        new_start=0, new_end=5.2, original_start=0, original_end=4, source="synthetic"
    )
    result = refine_candidate_dtw_details(
        Audio(source, sr, 4),
        Audio(target, sr, 5.2),
        coarse,
        max_pitch_shift_semitones=4,
    )
    assert result.accepted
    assert result.pitch_shift_semitones == 3
    # Flat note interiors do not establish an exact boundary; retain the same
    # sub-second localization tolerance as the untransformed-copy control.
    assert abs(result.interval.new_start) < 0.6
    assert abs(result.interval.new_end - 5.2) < 0.7
    assert 0.5 <= result.duration_ratio <= 1.5


def test_slope_limited_path_cannot_collapse_query_on_one_target_frame():
    from lastrada.alignment.dtw import _subsequence_dtw

    cost = np.ones((80, 100))
    cost[:, 50] = 0
    path, _ = _subsequence_dtw(cost)
    assert np.ptp(path[:, 1]) >= 39
