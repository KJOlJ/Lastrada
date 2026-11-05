"""Compare candidate regions across estimated Demucs stems.

Stem labels and audio are model estimates. Results are supporting evidence only;
they do not establish that the sampled element is definitively guitar, vocals,
drums, or another instrument.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from concurrent.futures import ThreadPoolExecutor

from lastrada.alignment.dtw import refine_candidate_dtw_details
from lastrada.schemas.models import Interval


@dataclass
class StemPairEvidence:
    source_stem: str
    derivative_stem: str
    accepted: bool
    reason: str
    mean_dtw_cost: float | None
    pitch_shift_semitones: int | None
    duration_ratio: float | None
    source_start: float
    source_end: float
    sony_new_start: float
    sony_new_end: float
    refined_new_start: float
    refined_new_end: float
    refined_duration: float
    same_label: bool
    sony_similarity: float | None

    def to_dict(self):
        return asdict(self)


@dataclass
class StemComparisonResult:
    source_region: object
    derivative_region: object
    evidence: list[StemPairEvidence]
    probe: Interval | None = None
    partial: bool = False

    @property
    def accepted(self) -> list[StemPairEvidence]:
        return [item for item in self.evidence if item.accepted]

    @property
    def best(self) -> StemPairEvidence | None:
        # For listening, prefer a separated accepted pair over the full-mix
        # baseline. The complete table still shows every ordered pair.
        for item in self.evidence:
            if item.accepted and (
                item.source_stem != "full_mix" or item.derivative_stem != "full_mix"
            ):
                return item
        for item in self.evidence:
            if item.accepted:
                return item
        return self.evidence[0] if self.evidence else None


def candidate_stem_pairs(
    source_stems,
    derivative_stems,
    *,
    include_cross_other: bool = True,
):
    """Return conservative stem pairs, avoiding an all-by-all explosion."""
    source = set(source_stems)
    derivative = set(derivative_stems)
    ordered = []

    preferred_order = [
        "full_mix",
        "guitar",
        "piano",
        "bass",
        "drums",
        "vocals",
        "other",
    ]
    for stem in preferred_order:
        if stem in source and stem in derivative:
            ordered.append((stem, stem))

    if include_cross_other:
        cross_pairs = [
            ("guitar", "other"),
            ("other", "guitar"),
            ("piano", "other"),
            ("other", "piano"),
        ]
        for pair in cross_pairs:
            if pair[0] in source and pair[1] in derivative and pair not in ordered:
                ordered.append(pair)

    return ordered


def bounded_stem_probe(interval, maximum=8.0):
    """Take a centered paired fraction; never expand or re-label the match."""
    if interval.original_start is None or interval.original_end is None:
        raise ValueError("Stem comparison requires source timestamps")
    if not 0 < maximum <= 8:
        raise ValueError("Stem probes must be at most eight seconds")
    widths = [interval.new_end - interval.new_start, interval.original_end - interval.original_start]
    fraction = min(1.0, maximum / max(widths))
    values = interval.model_dump()
    values.update(end_review=None, ending_review_context=None)
    for prefix, width in zip(("new", "original"), widths):
        start, end = getattr(interval, prefix + "_start"), getattr(interval, prefix + "_end")
        left = start + (width - width * fraction) / 2
        values[prefix + "_start"] = left
        values[prefix + "_end"] = end if fraction == 1 else left + width * fraction
    return Interval.model_validate(values)


def probe_is_partial(probe, interval):
    return any(
        getattr(probe, key) != getattr(interval, key)
        for key in ("new_start", "new_end", "original_start", "original_end")
    )


def compare_candidate_stems(
    original,
    new,
    interval: Interval,
    separator,
    *,
    separation_padding: float = 4.0,
    dtw_search_padding: float = 2.0,
    max_pitch_shift_semitones: int = 6,
    minimum_duration_ratio: float = 0.5,
    maximum_duration_ratio: float = 1.5,
    minimum_duration: float = 0.5,
    include_cross_other: bool = True,
    parallel_separation: bool = False,
) -> StemComparisonResult:
    """Compare bounded paired crops; return their exact scope with the evidence."""
    if interval.original_start is None or interval.original_end is None:
        raise ValueError("Stem comparison requires source timestamps")
    candidate = interval
    interval = bounded_stem_probe(candidate)

    def separate(audio, start, end):
        return separator.separate_region(audio, start, end, padding_seconds=separation_padding)

    if parallel_separation:
        # Only the bounded per-occurrence path opts in. Main analysis may still
        # retain Sony in memory and uses sequential separation.
        with ThreadPoolExecutor(max_workers=2) as pool:
            source = pool.submit(separate, original, interval.original_start, interval.original_end)
            derivative = pool.submit(separate, new, interval.new_start, interval.new_end)
            source_region, derivative_region = source.result(), derivative.result()
    else:
        source_region = separate(original, interval.original_start, interval.original_end)
        derivative_region = separate(new, interval.new_start, interval.new_end)

    local_interval = Interval(
        new_start=derivative_region.candidate_start_local,
        new_end=derivative_region.candidate_end_local,
        original_start=source_region.candidate_start_local,
        original_end=source_region.candidate_end_local,
        source="stem_assisted_candidate",
        status="candidate",
        similarity=interval.similarity,
    )

    evidence = []
    pairs = candidate_stem_pairs(
        source_region.stems,
        derivative_region.stems,
        include_cross_other=include_cross_other,
    )

    for source_stem, derivative_stem in pairs:
        detail = refine_candidate_dtw_details(
            source_region.stems[source_stem],
            derivative_region.stems[derivative_stem],
            local_interval,
            search_padding=dtw_search_padding,
            max_pitch_shift_semitones=max_pitch_shift_semitones,
            minimum_duration_ratio=minimum_duration_ratio,
            maximum_duration_ratio=maximum_duration_ratio,
            minimum_duration=minimum_duration,
        )

        local_refined = detail.interval
        refined_start = derivative_region.offset_seconds + local_refined.new_start
        refined_end = derivative_region.offset_seconds + local_refined.new_end
        refined_duration = refined_end - refined_start

        evidence.append(
            StemPairEvidence(
                source_stem=source_stem,
                derivative_stem=derivative_stem,
                accepted=detail.accepted,
                reason=detail.reason,
                mean_dtw_cost=detail.mean_cost,
                pitch_shift_semitones=detail.pitch_shift_semitones,
                duration_ratio=detail.duration_ratio,
                source_start=interval.original_start,
                source_end=interval.original_end,
                sony_new_start=interval.new_start,
                sony_new_end=interval.new_end,
                refined_new_start=float(refined_start),
                refined_new_end=float(refined_end),
                refined_duration=float(refined_duration),
                same_label=source_stem == derivative_stem,
                sony_similarity=interval.similarity,
            )
        )

    # Accepted results first; among those, same-label evidence and lower DTW cost
    # rank higher. This is only an ordering rule, not a confidence calculation.
    evidence.sort(
        key=lambda item: (
            not item.accepted,
            not item.same_label,
            float("inf") if item.mean_dtw_cost is None else item.mean_dtw_cost,
            item.source_stem,
            item.derivative_stem,
        )
    )
    return StemComparisonResult(
        source_region, derivative_region, evidence,
        probe=interval, partial=probe_is_partial(interval, candidate),
    )
