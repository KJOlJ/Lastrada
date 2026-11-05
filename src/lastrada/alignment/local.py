"""Bounded direct-waveform refinement; uncertain alignments keep coarse candidates."""

import numpy as np
from scipy.signal import correlate
from lastrada.schemas.models import EndReview, Interval


def refine_candidate(original, new, interval, radius=1.0, minimum_correlation=0.75):
    """Locate a distinctive anchor, then validate a contiguous matching extension.

    The first two seconds establish the lag. Every additional half-second block
    must independently pass the same correlation threshold. If no continuation
    matches, quarter-second checks can trim an unsupported anchor ending. This
    estimates boundaries, not a verified sampling decision.
    """
    if (
        original.sample_rate != new.sample_rate
        or interval.original_start is None
        or interval.original_end is None
    ):
        return interval
    sr = new.sample_rate
    source = original.samples[int(interval.original_start * sr) : int(interval.original_end * sr)]
    anchor = source[: 2 * sr]
    if len(anchor) < sr // 2 or np.linalg.norm(anchor) < 1e-8:
        return interval
    left = max(0, int((interval.new_start - radius) * sr))
    right = min(len(new.samples), int((interval.new_start + radius) * sr) + len(anchor))
    target = new.samples[left:right]
    if len(target) < len(anchor):
        return interval
    # FFT roundoff in silent windows must not become a large normalized score.
    # Float64 limits cancellation, and zero-energy windows remain ineligible.
    numerator = correlate(
        target.astype(np.float64), anchor.astype(np.float64), mode="valid", method="fft"
    )
    cumulative = np.cumsum(np.r_[0, target.astype(np.float64) ** 2])
    energies = cumulative[len(anchor) :] - cumulative[: -len(anchor)]
    denominator = np.sqrt(np.maximum(energies, 0.0)) * np.linalg.norm(anchor.astype(np.float64))
    scores = np.zeros_like(numerator)
    np.divide(numerator, denominator, out=scores, where=energies > 1e-12)
    best = int(np.argmax(scores))
    if scores[best] < minimum_correlation:
        return interval

    # A periodic tone or two equally plausible lags cannot select a precise start.
    alternatives = scores.copy()
    near_peak = max(1, int(0.1 * sr))
    alternatives[max(0, best - near_peak) : best + near_peak + 1] = -np.inf
    if np.max(alternatives) > scores[best] - 0.05:
        return interval

    offset = left + best
    limit = min(
        len(source),
        len(new.samples) - offset,
        int((interval.new_end + radius) * sr) - offset,
    )
    if limit < len(anchor):
        return interval
    matched_length = len(anchor)
    block_length = max(1, int(0.5 * sr))
    for block_start in range(matched_length, limit, block_length):
        block_end = min(block_start + block_length, limit)
        if block_end - block_start < sr // 10:
            break
        source_block = source[block_start:block_end].astype(np.float64)
        target_block = new.samples[offset + block_start : offset + block_end].astype(np.float64)
        energy = np.linalg.norm(source_block) * np.linalg.norm(target_block)
        if energy < 1e-10 or float(source_block @ target_block / energy) < minimum_correlation:
            break
        matched_length = block_end

    # An aggregate two-second score can hide the end of a shorter copy. Only
    # inspect that ending when the existing extension found no continuation;
    # a brief weak block inside a longer match must not truncate the passage.
    if matched_length == len(anchor):
        step = max(1, int(0.25 * sr))
        boundary = len(anchor)
        while boundary - step >= sr // 2:
            source_block = source[boundary - step : boundary].astype(np.float64)
            target_block = new.samples[offset + boundary - step : offset + boundary].astype(
                np.float64
            )
            energy = np.linalg.norm(source_block) * np.linalg.norm(target_block)
            if (
                energy >= 1e-10
                and float(source_block @ target_block / energy) >= minimum_correlation
            ):
                break
            boundary -= step
        if boundary < len(anchor):
            source_prefix = source[:boundary].astype(np.float64)
            target_prefix = new.samples[offset : offset + boundary].astype(np.float64)
            energy = np.linalg.norm(source_prefix) * np.linalg.norm(target_prefix)
            if (
                energy >= 1e-10
                and float(source_prefix @ target_prefix / energy) >= minimum_correlation
            ):
                matched_length = boundary

    start = offset / sr
    # Weak correlation cannot distinguish an absent tail from a quiet copied
    # tail under another sound. Keep the estimate, but preserve the untrimmed
    # anchor extent for listening review instead of implying a precise cutoff.
    end_review = (
        EndReview(
            new_through=(offset + len(anchor)) / sr,
            original_through=interval.original_start + len(anchor) / sr,
        )
        if matched_length < len(anchor)
        else None
    )
    return Interval(
        new_start=start,
        new_end=(offset + matched_length) / sr,
        original_start=interval.original_start,
        original_end=interval.original_start + matched_length / sr,
        source="direct_waveform_local_alignment",
        status="candidate",
        similarity=float(np.clip(scores[best], -1, 1)),
        end_review=end_review,
    )
