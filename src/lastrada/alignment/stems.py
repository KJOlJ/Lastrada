"""Compare candidate regions across like-for-like estimated Demucs stems.

Stem labels and audio are model estimates. Results are supporting evidence only;
they do not establish that the sampled element is definitively guitar, vocals,
drums, or another instrument.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

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

    @property
    def accepted(self) -> list[StemPairEvidence]:
        return [item for item in self.evidence if item.accepted]

    @property
    def best(self) -> StemPairEvidence | None:
        # Prefer a separated accepted pair over the full-mix baseline.
        for item in self.evidence:
            if item.accepted and (
                item.source_stem != "full_mix"
                or item.derivative_stem != "full_mix"
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
    include_cross_other: bool = False,
):
    """Return only like-for-like stem pairs that exist in both recordings.

    ``include_cross_other`` remains in the signature for backwards compatibility,
    but it is intentionally ignored. Cross-stem comparisons waste compute and are
    not used as supporting evidence in the production workflow.
    """
    del include_cross_other
    source = set(source_stems)
    derivative = set(derivative_stems)
    preferred_order = [
        "full_mix",
        "guitar",
        "piano",
        "bass",
        "drums",
        "vocals",
        "other",
    ]
    return [
        (stem, stem)
        for stem in preferred_order
        if stem in source and stem in derivative
    ]


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
    include_cross_other: bool = False,
) -> StemComparisonResult:
    """Separate both regions and run guarded DTW on matching stem labels only."""
    if interval.original_start is None or interval.original_end is None:
        raise ValueError("Stem comparison requires source timestamps")

    source_region = separator.separate_region(
        original,
        interval.original_start,
        interval.original_end,
        padding_seconds=separation_padding,
    )
    derivative_region = separator.separate_region(
        new,
        interval.new_start,
        interval.new_end,
        padding_seconds=separation_padding,
    )

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
        refined_start = (
            derivative_region.offset_seconds + local_refined.new_start
        )
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
                same_label=True,
                sony_similarity=interval.similarity,
            )
        )

    evidence.sort(
        key=lambda item: (
            not item.accepted,
            float("inf") if item.mean_dtw_cost is None else item.mean_dtw_cost,
            item.source_stem,
        )
    )
    return StemComparisonResult(source_region, derivative_region, evidence)
