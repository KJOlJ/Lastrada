"""Known-copy boundary checks and ambiguity controls; no historical audio."""

import numpy as np
import pytest

from lastrada.alignment.local import refine_candidate
from lastrada.audio.io import Audio
from lastrada.schemas.models import Interval


def fixture(length=6, sr=8000):
    rng = np.random.default_rng(381)
    source = rng.normal(0, 0.2, 10 * sr).astype(np.float32)
    target = rng.normal(0, 0.02, 14 * sr).astype(np.float32)
    left, count = int(2.75 * sr), int(length * sr)
    target[left : left + count] += source[sr : sr + count]
    candidate = Interval(
        new_start=3,
        new_end=12,
        original_start=1,
        original_end=9,
        source="sampleid_rank_sequence",
        similarity=0.9,
    )
    return Audio(source, sr, 10), Audio(target, sr, 14), candidate


@pytest.mark.parametrize("length", [2, 3.5, 6, 8])
@pytest.mark.parametrize("sr", [8000, 16000])
def test_direct_alignment_recovers_long_copy_end_in_a_mix(length, sr):
    source, target, coarse = fixture(length, sr)
    result = refine_candidate(source, target, coarse)
    assert result.source == "direct_waveform_local_alignment"
    assert result.new_start == pytest.approx(2.75)
    assert result.new_end == pytest.approx(2.75 + length)
    assert result.original_start == 1
    assert result.original_end == pytest.approx(1 + length)
    assert result.status == "candidate"


def test_a_gap_stops_extension_even_if_later_blocks_match():
    source, target, coarse = fixture(8)
    sr = source.sample_rate
    # Remove a half-second from the copied passage but retain later matching audio.
    target.samples[int(5.25 * sr) : int(5.75 * sr)] = 0
    result = refine_candidate(source, target, coarse)
    assert result.new_end == pytest.approx(5.25)


@pytest.mark.parametrize("source_end,new_end", [(4, 12), (9, 5)])
def test_extension_stays_within_source_and_local_search_bounds(source_end, new_end):
    source, target, coarse = fixture(8)
    coarse.original_end, coarse.new_end = source_end, new_end
    result = refine_candidate(source, target, coarse)
    assert result.source == "direct_waveform_local_alignment"
    assert result.original_end <= source_end
    assert result.new_end <= new_end + 1


def test_two_equally_supported_starts_do_not_produce_a_precise_claim():
    source, target, coarse = fixture()
    sr = source.sample_rate
    target.samples[:] = 0
    for start in [2, 4]:
        target.samples[start * sr : (start + 2) * sr] = source.samples[sr : 3 * sr]
    assert refine_candidate(source, target, coarse) == coarse


@pytest.mark.parametrize("kind", ["tone", "silence", "unrelated"])
def test_uninformative_or_unrelated_audio_retains_coarse_candidate(kind):
    source, target, coarse = fixture()
    sr = source.sample_rate
    if kind == "tone":
        source.samples = np.sin(2 * np.pi * 440 * np.arange(10 * sr) / sr).astype(np.float32)
        target.samples = np.sin(2 * np.pi * 440 * np.arange(14 * sr) / sr).astype(np.float32)
    elif kind == "silence":
        source.samples[:] = target.samples[:] = 0
    else:
        target.samples = np.random.default_rng(936).normal(size=14 * sr).astype(np.float32)
    assert refine_candidate(source, target, coarse) == coarse
