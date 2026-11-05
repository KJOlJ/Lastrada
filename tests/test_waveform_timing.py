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
    assert result.end_review is None


@pytest.mark.parametrize("length", [1.25, 1.5, 1.75])
@pytest.mark.parametrize("sr", [8000, 16000])
def test_short_copy_does_not_claim_the_whole_two_second_anchor(length, sr):
    source, target, coarse = fixture(length, sr)
    result = refine_candidate(source, target, coarse, radius=5)
    assert result.source == "direct_waveform_local_alignment"
    assert (result.new_start, result.new_end) == pytest.approx((2.75, 2.75 + length))
    assert (result.original_start, result.original_end) == pytest.approx((1, 1 + length))
    assert result.status == "candidate"
    assert result.end_review.new_through == pytest.approx(4.75)
    assert result.end_review.original_through == pytest.approx(3)


def test_brief_weak_anchor_block_does_not_truncate_a_longer_copy():
    source, target, coarse = fixture(8)
    sr = source.sample_rate
    target.samples[int(3.75 * sr) : int(4 * sr)] = 0
    result = refine_candidate(source, target, coarse)
    assert result.source == "direct_waveform_local_alignment"
    assert result.new_end == pytest.approx(10.75)
    assert result.original_end == pytest.approx(9)


def test_weak_interior_block_does_not_shorten_a_supported_anchor_ending():
    source, target, coarse = fixture(2)
    sr = source.sample_rate
    target.samples[int(3.25 * sr) : int(3.5 * sr)] = 0
    result = refine_candidate(source, target, coarse)
    assert result.source == "direct_waveform_local_alignment"
    assert result.new_end == pytest.approx(4.75)


@pytest.mark.parametrize("length", [1.4, 1.9])
def test_short_non_grid_boundary_stays_within_a_quarter_second(length):
    source, target, coarse = fixture(length)
    result = refine_candidate(source, target, coarse)
    assert result.source == "direct_waveform_local_alignment"
    assert abs(result.new_end - (2.75 + length)) <= 0.25
    assert abs(result.original_end - (1 + length)) <= 0.25


def test_subsecond_copy_still_needs_the_existing_anchor_acceptance():
    source, target, coarse = fixture(0.75)
    assert refine_candidate(source, target, coarse) == coarse


def test_short_source_window_can_still_be_refined():
    source, target, coarse = fixture(0.5)
    coarse.original_end = 1.5
    result = refine_candidate(source, target, coarse)
    assert result.source == "direct_waveform_local_alignment"
    assert result.new_end == pytest.approx(3.25)
    assert result.end_review is None


@pytest.mark.parametrize("tail", [0.25, 0.5])
@pytest.mark.parametrize("gain", [0, 0.01, 0.03])
def test_absent_and_obscured_tails_both_expose_ending_uncertainty(tail, gain):
    source, target, coarse = fixture(2)
    sr = source.sample_rate
    start = int((2.75 + 2 - tail) * sr)
    end = int(4.75 * sr)
    copied_tail = source.samples[int((3 - tail) * sr) : 3 * sr]
    target.samples[start:end] -= (1 - gain) * copied_tail
    result = refine_candidate(source, target, coarse)
    assert result.source == "direct_waveform_local_alignment"
    # The same estimate can mean an absent tail or a real but obscured tail.
    # Neither gets an unqualified endpoint or a claim of verified reuse.
    assert result.new_end == pytest.approx(4.75 - tail)
    assert result.end_review.new_through == pytest.approx(4.75)
    assert result.end_review.original_through == pytest.approx(3)
    assert result.status == "candidate"
    assert Interval.model_validate_json(result.model_dump_json()) == result


def test_unrelated_audio_does_not_gain_an_uncertainty_match():
    source, target, coarse = fixture(0)
    result = refine_candidate(source, target, coarse)
    assert result == coarse
    assert result.end_review is None


def test_legacy_interval_has_no_ending_cue():
    interval = Interval.model_validate({"new_start": 1, "new_end": 2, "source": "old"})
    assert interval.end_review is None


def test_ending_review_extent_must_follow_both_endpoints():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="Ending review must extend"):
        Interval(
            new_start=1, new_end=2, original_start=3, original_end=4, source="test",
            end_review={"new_through": 1.5, "original_through": 5},
        )


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
