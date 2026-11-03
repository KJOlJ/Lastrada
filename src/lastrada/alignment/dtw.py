"""Guarded chroma + subsequence DTW refinement for SampleID candidates.

This module is intentionally a *refiner*, not a detector. It only runs after
SampleID has proposed a source/new-work interval pair. If DTW cannot produce a
plausible alignment under conservative duration-ratio guardrails, the original
coarse candidate is returned unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
from scipy.signal import resample_poly, stft

from lastrada.schemas.models import Interval


@dataclass
class DTWRefinementResult:
    """Detailed evidence from one guarded DTW attempt.

    `accepted` only means that the alignment passed the configured engineering
    guardrails. It is not a probability or verified sample conclusion.
    """

    interval: Interval
    accepted: bool
    reason: str
    mean_cost: float | None = None
    pitch_shift_semitones: int | None = None
    duration_ratio: float | None = None
    source_duration: float | None = None
    derivative_duration: float | None = None
    search_start: float | None = None
    search_end: float | None = None
    path_points: int = 0


def _resample(samples: np.ndarray, source_rate: int, target_rate: int) -> np.ndarray:
    if source_rate == target_rate:
        return samples.astype(np.float32, copy=False)
    divisor = math.gcd(source_rate, target_rate)
    return resample_poly(samples, target_rate // divisor, source_rate // divisor).astype(np.float32)


def _segment(audio, start: float, end: float, sample_rate: int) -> np.ndarray:
    y = _resample(audio.samples, audio.sample_rate, sample_rate)
    left = max(0, int(round(start * sample_rate)))
    right = min(len(y), int(round(end * sample_rate)))
    if right <= left:
        return np.empty(0, dtype=np.float32)
    return y[left:right]


def _chroma(
    samples: np.ndarray,
    sample_rate: int,
    nperseg: int = 2048,
    hop: int = 512,
):
    """Small dependency-free chroma representation built from an STFT."""
    if len(samples) < max(512, nperseg // 2):
        return np.empty((12, 0), dtype=np.float64)

    frame_size = min(nperseg, len(samples))
    _, _, z = stft(
        samples,
        fs=sample_rate,
        nperseg=frame_size,
        noverlap=max(0, frame_size - hop),
        boundary=None,
        padded=True,
    )
    magnitude = np.abs(z).astype(np.float64)
    freqs = np.fft.rfftfreq(frame_size, d=1.0 / sample_rate)

    valid = freqs >= 55.0
    freqs = freqs[valid]
    magnitude = magnitude[valid]
    if not len(freqs):
        return np.empty((12, 0), dtype=np.float64)

    midi = 69.0 + 12.0 * np.log2(freqs / 440.0)
    pitch_classes = np.mod(np.rint(midi).astype(int), 12)

    chroma = np.zeros((12, magnitude.shape[1]), dtype=np.float64)
    for pitch_class in range(12):
        mask = pitch_classes == pitch_class
        if np.any(mask):
            chroma[pitch_class] = magnitude[mask].sum(axis=0)

    # Remove the shared broadband floor: unrelated noise must not appear similar
    # merely because all twelve pitch classes have energy.
    chroma = np.sqrt(np.maximum(chroma, 0.0))
    chroma -= chroma.mean(axis=0, keepdims=True)
    norms = np.linalg.norm(chroma, axis=0, keepdims=True)
    chroma /= np.maximum(norms, 1e-12)
    return chroma


def _local_cost(source: np.ndarray, target: np.ndarray) -> np.ndarray:
    return np.maximum(0.0, 1.0 - np.clip(source.T @ target, -1.0, 1.0))


def _subsequence_dtw(cost: np.ndarray):
    """Slope-limited subsequence DTW; never collapse a phrase onto one frame.

    Steps consume (source, target) frames in ratios 1:1, 1:2 or 2:1.
    Costs are weighted by source frames so paths have comparable objectives.
    """
    m, n = cost.shape
    if not m or not n:
        return None, float("inf")
    accumulated = np.full((m, n), np.inf)
    back = np.full((m, n), -1, dtype=np.int8)
    accumulated[0] = cost[0]
    for i in range(1, m):
        choices = np.full((3, n), np.inf)
        choices[0, 1:] = accumulated[i - 1, :-1] + cost[i, 1:]
        choices[1, 2:] = accumulated[i - 1, :-2] + cost[i, 2:]
        if i > 1:
            choices[2, 1:] = accumulated[i - 2, :-1] + cost[i - 1, 1:] + cost[i, 1:]
        back[i] = np.argmin(choices, axis=0)
        accumulated[i] = np.min(choices, axis=0)
    j = int(np.argmin(accumulated[-1]))
    if not np.isfinite(accumulated[-1, j]):
        return None, float("inf")
    mean_cost = float(accumulated[-1, j] / m)
    i = m - 1
    path = [(i, j)]
    while i > 0:
        move = back[i, j]
        if move == 0:
            i, j = i - 1, j - 1
        elif move == 1:
            i, j = i - 1, j - 2
        else:
            path.append((i - 1, j))
            i, j = i - 2, j - 1
        path.append((i, j))
    return np.asarray(path[::-1], dtype=int), mean_cost


def duration_ratio_is_plausible(
    source_duration: float,
    derivative_duration: float,
    minimum_ratio: float = 0.5,
    maximum_ratio: float = 1.5,
) -> bool:
    if source_duration <= 0 or derivative_duration <= 0:
        return False
    ratio = derivative_duration / source_duration
    return minimum_ratio <= ratio <= maximum_ratio


def _rejected(
    interval: Interval,
    reason: str,
    *,
    source_duration: float | None = None,
    search_start: float | None = None,
    search_end: float | None = None,
) -> DTWRefinementResult:
    return DTWRefinementResult(
        interval=interval,
        accepted=False,
        reason=reason,
        source_duration=source_duration,
        search_start=search_start,
        search_end=search_end,
    )


def refine_candidate_dtw_details(
    original,
    new,
    interval: Interval,
    *,
    search_padding: float = 4.0,
    max_pitch_shift_semitones: int = 6,
    minimum_duration_ratio: float = 0.5,
    maximum_duration_ratio: float = 1.5,
    minimum_duration: float = 0.5,
    analysis_rate: int = 16000,
    hop: int = 512,
) -> DTWRefinementResult:
    """Refine one candidate and return alignment evidence plus the interval."""
    if interval.original_start is None or interval.original_end is None:
        return _rejected(interval, "source timestamps unavailable")
    if interval.original_end <= interval.original_start:
        return _rejected(interval, "invalid source interval")

    source_duration = interval.original_end - interval.original_start
    if source_duration < minimum_duration:
        return _rejected(
            interval,
            "source interval shorter than minimum duration",
            source_duration=source_duration,
        )

    search_start = max(0.0, interval.new_start - search_padding)
    search_end = min(new.duration, interval.new_end + search_padding)
    if search_end - search_start < minimum_duration:
        return _rejected(
            interval,
            "derivative search region shorter than minimum duration",
            source_duration=source_duration,
            search_start=search_start,
            search_end=search_end,
        )

    source_y = _segment(
        original,
        interval.original_start,
        interval.original_end,
        analysis_rate,
    )
    target_y = _segment(new, search_start, search_end, analysis_rate)
    source_chroma = _chroma(source_y, analysis_rate, hop=hop)
    target_chroma = _chroma(target_y, analysis_rate, hop=hop)

    if source_chroma.shape[1] < 2 or target_chroma.shape[1] < 2:
        return _rejected(
            interval,
            "not enough chroma frames",
            source_duration=source_duration,
            search_start=search_start,
            search_end=search_end,
        )

    # A steady note/chord cannot identify a particular sampled phrase. Require
    # temporal information in addition to a low distance. These engineering
    # thresholds are abstention rules, not calibrated detection probabilities.
    temporal_variation = float(np.mean(np.var(source_chroma, axis=1)))
    if temporal_variation < 0.002:
        return _rejected(interval, "insufficient changing pitch information")

    best = None
    seconds_per_frame = hop / analysis_rate

    for shift in range(-max_pitch_shift_semitones, max_pitch_shift_semitones + 1):
        shifted = np.roll(source_chroma, shift, axis=0)
        path, mean_cost = _subsequence_dtw(_local_cost(shifted, target_chroma))
        if path is None or not len(path):
            continue

        # A good fit must also beat the reversed query. Shared timbre or a
        # stationary background alone should not count as ordered support.
        _, reversed_cost = _subsequence_dtw(_local_cost(shifted[:, ::-1], target_chroma))
        if mean_cost > 0.30 or reversed_cost - mean_cost < 0.04:
            continue

        matched_target_frames = path[:, 1]
        refined_start = search_start + float(matched_target_frames.min()) * seconds_per_frame
        refined_end = (
            search_start
            + float(matched_target_frames.max()) * seconds_per_frame
            + min(2048, len(source_y)) / analysis_rate
        )
        refined_start = max(0.0, refined_start)
        refined_end = min(new.duration, refined_end)
        derivative_duration = refined_end - refined_start

        if derivative_duration < minimum_duration:
            continue
        if not duration_ratio_is_plausible(
            source_duration,
            derivative_duration,
            minimum_duration_ratio,
            maximum_duration_ratio,
        ):
            continue
        if refined_end <= interval.new_start or refined_start >= interval.new_end:
            continue

        candidate = {
            "mean_cost": float(mean_cost),
            "pitch_shift": int(shift),
            "refined_start": float(refined_start),
            "refined_end": float(refined_end),
            "duration": float(derivative_duration),
            "path_points": int(len(path)),
        }
        if best is None or candidate["mean_cost"] < best["mean_cost"]:
            best = candidate

    if best is None:
        return _rejected(
            interval,
            "no distinctive alignment passed content, overlap and duration guardrails",
            source_duration=source_duration,
            search_start=search_start,
            search_end=search_end,
        )

    refined = Interval(
        new_start=best["refined_start"],
        new_end=best["refined_end"],
        original_start=interval.original_start,
        original_end=interval.original_end,
        source="dtw_chroma_local_alignment",
        status="candidate",
        similarity=interval.similarity,
    )
    return DTWRefinementResult(
        interval=refined,
        accepted=True,
        reason="alignment passed content, slope and duration guardrails; listening required",
        mean_cost=best["mean_cost"],
        pitch_shift_semitones=best["pitch_shift"],
        duration_ratio=best["duration"] / source_duration,
        source_duration=source_duration,
        derivative_duration=best["duration"],
        search_start=search_start,
        search_end=search_end,
        path_points=best["path_points"],
    )


def refine_candidate_dtw(
    original,
    new,
    interval: Interval,
    **kwargs,
):
    """Compatibility wrapper returning only the refined or original interval."""
    return refine_candidate_dtw_details(original, new, interval, **kwargs).interval
