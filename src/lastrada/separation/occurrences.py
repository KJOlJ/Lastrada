"""Grouped representative stem checks for the production review flow.

Sony/DTW timestamp candidates are first collapsed into relationship groups. Demucs
and stem-level DTW then run once for a representative paired occurrence from each
group. The resulting evidence supports the full group and never replaces listening
review.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from time import monotonic

from lastrada.alignment.stems import compare_candidate_stems
from lastrada.pipeline import _stem_evidence_records, short_stem_candidate
from lastrada.reporting.suggestions import suggested_intervals
from lastrada.schemas.models import InstrumentOccurrence, Interval
from lastrada.separation.demucs import DemucsSeparator, StemSeparationUnavailable

LABELS = {
    "bass": "Bass",
    "drums": "Drums",
    "vocals": "Vocals",
    "other": "Other sounds (unidentified)",
    "guitar": "Guitar",
    "piano": "Piano",
}
FINAL = {"checked", "no_source", "too_short", "failed"}
MIN_PROBE_SECONDS = 2.0
EPSILON = 1e-9


@dataclass
class RelationshipGroup:
    group_number: int
    raw_candidates: list[Interval]
    occurrences: list[Interval]
    source_passages: list[tuple[float, float]]
    representative: Interval
    representative_selection: str
    group_id: str


def _duration(start: float | None, end: float | None) -> float:
    if start is None or end is None:
        return 0.0
    return max(0.0, float(end) - float(start))


def _overlap_ratio(
    a_start: float | None,
    a_end: float | None,
    b_start: float | None,
    b_end: float | None,
) -> float:
    if None in (a_start, a_end, b_start, b_end):
        return 0.0
    overlap = max(0.0, min(a_end, b_end) - max(a_start, b_start))
    denominator = max(
        EPSILON,
        min(_duration(a_start, a_end), _duration(b_start, b_end)),
    )
    return overlap / denominator


def _representative_source(intervals: list[Interval]) -> tuple[float | None, float | None]:
    starts = [item.original_start for item in intervals if item.original_start is not None]
    ends = [item.original_end for item in intervals if item.original_end is not None]
    if not starts or not ends:
        return None, None
    return float(median(starts)), float(median(ends))


def _source_family_score(interval: Interval, family: list[Interval]) -> float:
    source_start, source_end = _representative_source(family)
    source_known = interval.original_start is not None and interval.original_end is not None
    if not source_known:
        return 1.0 if source_start is None else -1.0
    if source_start is None or source_end is None:
        return -1.0

    overlap = _overlap_ratio(
        interval.original_start,
        interval.original_end,
        source_start,
        source_end,
    )
    if overlap >= 0.35:
        return 2.0 + overlap

    center = (interval.original_start + interval.original_end) / 2
    family_center = (source_start + source_end) / 2
    tolerance = max(
        2.0,
        0.25
        * max(
            _duration(interval.original_start, interval.original_end),
            _duration(source_start, source_end),
        ),
    )
    distance = abs(center - family_center)
    return 1.0 - distance / max(tolerance, EPSILON) if distance <= tolerance else -1.0


def _same_new_occurrence(left: Interval, right: Interval) -> bool:
    overlap = _overlap_ratio(
        left.new_start,
        left.new_end,
        right.new_start,
        right.new_end,
    )
    if overlap >= 0.5:
        return True

    left_center = (left.new_start + left.new_end) / 2
    right_center = (right.new_start + right.new_end) / 2
    left_duration = _duration(left.new_start, left.new_end)
    right_duration = _duration(right.new_start, right.new_end)
    duration_ratio = max(left_duration, right_duration) / max(
        EPSILON, min(left_duration, right_duration)
    )
    return abs(left_center - right_center) <= 0.75 and duration_ratio <= 2.0


def _collapse_new_occurrences(intervals: list[Interval]) -> list[Interval]:
    clusters: list[list[Interval]] = []
    for interval in sorted(intervals, key=lambda item: (item.new_start, item.new_end)):
        match = next(
            (
                cluster
                for cluster in clusters
                if any(_same_new_occurrence(interval, old) for old in cluster)
            ),
            None,
        )
        if match is None:
            clusters.append([interval])
        else:
            match.append(interval)

    def preferred(cluster: list[Interval]) -> Interval:
        return max(
            cluster,
            key=lambda item: (
                item.similarity if item.similarity is not None else -2.0,
                _duration(item.new_start, item.new_end),
                -item.new_start,
            ),
        )

    return sorted(
        (preferred(cluster) for cluster in clusters),
        key=lambda item: (item.new_start, item.new_end),
    )


def _source_passages(intervals: list[Interval]) -> list[tuple[float, float]]:
    start, end = _representative_source(intervals)
    return [] if start is None or end is None else [(start, end)]


def _dedupe_source_passages(
    passages: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for passage in passages:
        if not any(
            _overlap_ratio(passage[0], passage[1], existing[0], existing[1]) >= 0.5
            for existing in result
        ):
            result.append(passage)
    return sorted(result)


def _occurrence_match_count(left: list[Interval], right: list[Interval]) -> int:
    used: set[int] = set()
    matches = 0
    for item in left:
        index = next(
            (
                candidate_index
                for candidate_index, candidate in enumerate(right)
                if candidate_index not in used and _same_new_occurrence(item, candidate)
            ),
            None,
        )
        if index is not None:
            used.add(index)
            matches += 1
    return matches


def _same_derivative_relationship(left: dict, right: dict) -> bool:
    if not left["occurrences"] or not right["occurrences"]:
        return False
    left_has_source = bool(left["source_passages"])
    right_has_source = bool(right["source_passages"])
    if left_has_source != right_has_source:
        return False
    matches = _occurrence_match_count(left["occurrences"], right["occurrences"])
    smaller = min(len(left["occurrences"]), len(right["occurrences"]))
    larger = max(len(left["occurrences"]), len(right["occurrences"]))
    return matches / smaller >= 0.75 and matches / larger >= 0.6


def _representative_score(interval: Interval) -> tuple[float, float, float, float, float]:
    new_duration = _duration(interval.new_start, interval.new_end)
    source_duration = _duration(interval.original_start, interval.original_end)
    similarity = interval.similarity if interval.similarity is not None else -2.0
    balance = -abs(math.log(max(EPSILON, new_duration / max(EPSILON, source_duration))))
    usable_duration = min(new_duration, source_duration)
    return similarity, balance, usable_duration, new_duration, -interval.new_start


def _choose_representative(
    occurrences: list[Interval],
    raw_candidates: list[Interval],
) -> tuple[Interval, str]:
    eligible = [
        item
        for item in occurrences
        if item.original_start is not None
        and item.original_end is not None
        and min(
            _duration(item.new_start, item.new_end),
            _duration(item.original_start, item.original_end),
        )
        >= MIN_PROBE_SECONDS
    ]
    if eligible:
        return max(eligible, key=_representative_score), (
            "Selected from the grouped uses by highest Sony similarity, then "
            "source/derivative duration balance and usable duration."
        )

    paired = [
        item
        for item in occurrences
        if item.original_start is not None and item.original_end is not None
    ]
    if paired:
        return max(
            paired,
            key=lambda item: (
                min(
                    _duration(item.new_start, item.new_end),
                    _duration(item.original_start, item.original_end),
                ),
                item.similarity if item.similarity is not None else -2.0,
            ),
        ), "No grouped occurrence was at least two seconds; retained the longest paired row."

    fallback = occurrences or raw_candidates
    return max(
        fallback,
        key=lambda item: (
            item.similarity if item.similarity is not None else -2.0,
            _duration(item.new_start, item.new_end),
        ),
    ), "Original-track timestamps were unavailable for this group."


def _group_id(
    source_passages: list[tuple[float, float]],
    occurrences: list[Interval],
) -> str:
    payload = {
        "source": [[round(start, 6), round(end, 6)] for start, end in source_passages],
        "derivative": [
            [
                round(item.new_start, 6),
                round(item.new_end, 6),
                None if item.original_start is None else round(item.original_start, 6),
                None if item.original_end is None else round(item.original_end, 6),
            ]
            for item in occurrences
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:24]


def relationship_groups(result) -> list[RelationshipGroup]:
    """Group overlapping/repeated timestamp candidates and select one probe per group."""

    intervals = [
        item
        for item in suggested_intervals(result, "master")
        if item.new_end > item.new_start
    ]
    if not intervals:
        return []

    raw_families: list[list[Interval]] = []
    ordered = sorted(
        intervals,
        key=lambda item: (
            0 if item.original_start is not None else 1,
            item.original_start if item.original_start is not None else float("inf"),
            item.new_start,
            item.new_end,
        ),
    )
    for interval in ordered:
        best_family = None
        best_score = -1.0
        for family in raw_families:
            score = _source_family_score(interval, family)
            if score > best_score:
                best_score = score
                best_family = family
        if best_family is None or best_score < 0:
            raw_families.append([interval])
        else:
            best_family.append(interval)

    source_families = []
    for family in raw_families:
        occurrences = _collapse_new_occurrences(family)
        if occurrences:
            source_families.append(
                {
                    "source_passages": _source_passages(family),
                    "raw_candidates": sorted(
                        family, key=lambda item: (item.new_start, item.new_end)
                    ),
                    "occurrences": occurrences,
                }
            )

    relationships: list[dict] = []
    for family in source_families:
        match = next(
            (
                relationship
                for relationship in relationships
                if _same_derivative_relationship(relationship, family)
            ),
            None,
        )
        if match is None:
            relationships.append(
                {
                    "source_passages": list(family["source_passages"]),
                    "raw_candidates": list(family["raw_candidates"]),
                    "occurrences": list(family["occurrences"]),
                }
            )
        else:
            match["source_passages"].extend(family["source_passages"])
            match["raw_candidates"].extend(family["raw_candidates"])
            match["occurrences"] = _collapse_new_occurrences(
                [*match["occurrences"], *family["occurrences"]]
            )

    relationships.sort(
        key=lambda relationship: (
            -len(relationship["occurrences"]),
            -len(relationship["raw_candidates"]),
            relationship["occurrences"][0].new_start,
        )
    )

    groups = []
    for group_number, relationship in enumerate(relationships, 1):
        occurrences = _collapse_new_occurrences(relationship["occurrences"])
        source_passages = _dedupe_source_passages(relationship["source_passages"])
        representative, selection = _choose_representative(
            occurrences,
            relationship["raw_candidates"],
        )
        groups.append(
            RelationshipGroup(
                group_number=group_number,
                raw_candidates=relationship["raw_candidates"],
                occurrences=occurrences,
                source_passages=source_passages,
                representative=representative,
                representative_selection=selection,
                group_id=_group_id(source_passages, occurrences),
            )
        )
    return groups


def occurrence_id(interval):
    """Legacy single-interval identity retained for compatibility with old results."""

    values = [
        getattr(interval, key)
        for key in ("new_start", "new_end", "original_start", "original_end")
    ]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()[:24]


def _related_interval(left: Interval, right: Interval) -> bool:
    if (
        abs(left.new_start - right.new_start) <= 0.05
        and abs(left.new_end - right.new_end) <= 0.05
        and (
            (
                left.original_start is None
                and right.original_start is None
                and left.original_end is None
                and right.original_end is None
            )
            or (
                left.original_start is not None
                and right.original_start is not None
                and left.original_end is not None
                and right.original_end is not None
                and abs(left.original_start - right.original_start) <= 0.05
                and abs(left.original_end - right.original_end) <= 0.05
            )
        )
    ):
        return True
    if _overlap_ratio(
        left.new_start,
        left.new_end,
        right.new_start,
        right.new_end,
    ) < 0.5:
        return False
    left_has_source = left.original_start is not None and left.original_end is not None
    right_has_source = right.original_start is not None and right.original_end is not None
    if not left_has_source or not right_has_source:
        return left_has_source == right_has_source
    return (
        _overlap_ratio(
            left.original_start,
            left.original_end,
            right.original_start,
            right.original_end,
        )
        >= 0.35
    )


def occurrence_rows(result):
    """Return one evidence row per grouped sample relationship."""

    previous = {row.occurrence_id: row for row in result.instrument_occurrences}
    legacy_rows = list(result.instrument_occurrences)
    rows = []
    for group in relationship_groups(result):
        row = previous.get(group.group_id)
        if row is None:
            legacy = next(
                (
                    old
                    for old in legacy_rows
                    if old.status == "checked"
                    and _related_interval(old.interval, group.representative)
                ),
                None,
            )
            row = (
                legacy.model_copy(deep=True)
                if legacy is not None
                else InstrumentOccurrence(
                    occurrence_id=group.group_id,
                    candidate_number=group.group_number,
                    interval=group.representative.model_copy(deep=True),
                )
            )
        row.occurrence_id = group.group_id
        row.candidate_number = group.group_number
        row.interval = group.representative.model_copy(deep=True)

        represented = len(group.occurrences)
        if group.representative.original_start is None:
            row.status, row.reason = (
                "no_source",
                f"Group {group.group_number} contains {represented} "
                "derivative use(s), but original-track times are unavailable.",
            )
        elif (
            min(
                _duration(
                    group.representative.new_start,
                    group.representative.new_end,
                ),
                _duration(
                    group.representative.original_start,
                    group.representative.original_end,
                ),
            )
            < MIN_PROBE_SECONDS
        ):
            row.status, row.reason = (
                "too_short",
                f"Group {group.group_number} has no paired representative of at "
                "least two seconds.",
            )
        elif row.status not in FINAL:
            row.status = "pending"
            row.reason = (
                f"Representative comparison pending for {represented} grouped "
                f"use(s). {group.representative_selection}"
            )
        rows.append(row)
    return rows


def instrument_check_complete(result):
    rows = occurrence_rows(result)
    return bool(rows) and all(row.status in FINAL for row in rows)


def instrument_progress(result):
    rows = occurrence_rows(result)
    groups = relationship_groups(result)
    return {
        "finished": sum(row.status in FINAL for row in rows),
        "total": len(rows),
        "checked": sum(row.status == "checked" for row in rows),
        "represented_uses": sum(len(group.occurrences) for group in groups),
    }


def instrument_prefill(result):
    labels = []
    for row in occurrence_rows(result):
        if row.status == "checked":
            for label in row.suggested_instruments:
                if label not in labels:
                    labels.append(label)
    if not labels:
        return {}
    return {"element": ", ".join(labels), "method": "Sampled the original recording"}


def run_occurrence_instruments(
    result,
    original,
    new,
    settings,
    *,
    separator=None,
    on_progress=None,
    budget_seconds=900,
    max_new_checks=20,
):
    """Run one Demucs + same-stem DTW comparison per timestamp relationship group."""

    updated = result.model_copy(deep=True)
    groups = relationship_groups(updated)
    group_by_id = {group.group_id: group for group in groups}
    updated.instrument_occurrences = occurrence_rows(updated)
    began = monotonic()
    count = 0
    failure_reason = None

    def persist():
        updated.methods["instruments"] = (
            "demucs_htdemucs_group_representative_v1; one comparison per "
            "timestamp relationship"
        )
        updated.timings_seconds["instrument_checks"] = monotonic() - began
        if on_progress:
            on_progress(updated)

    persist()
    for row in updated.instrument_occurrences:
        if row.status in FINAL:
            continue
        remaining = budget_seconds - (monotonic() - began)
        if count >= max_new_checks or remaining < 20:
            failure_reason = (
                "Integrated group stem analysis reached its compute budget before "
                "all relationship groups could be checked."
            )
            break

        if separator is None:
            try:
                separator = DemucsSeparator(
                    model_name=settings.stem_model_name,
                    device=settings.stem_device,
                    cache_dir=Path(os.getenv("LASTRADA_CACHE_DIR", "cache")) / "demucs",
                    segment_seconds=4,
                    timeout_seconds=settings.stem_timeout_seconds,
                )
            except (StemSeparationUnavailable, OSError, RuntimeError, ValueError) as exc:
                failure_reason = str(exc)
                row.status, row.reason = "failed", failure_reason
                persist()
                break

        separator.timeout_seconds = max(
            1,
            min(
                settings.stem_timeout_seconds,
                int(max(1, (remaining - 10) / 2)),
            ),
        )
        row.probe = short_stem_candidate(
            [row.interval],
            min(8.0, settings.stem_probe_seconds),
        )
        row.evidence, row.suggested_instruments = [], []
        group = group_by_id[row.occurrence_id]
        represented = len(group.occurrences)

        try:
            comparison = compare_candidate_stems(
                original,
                new,
                row.probe,
                separator,
                separation_padding=1,
                dtw_search_padding=1,
                max_pitch_shift_semitones=2,
                minimum_duration_ratio=0.5,
                maximum_duration_ratio=2,
                minimum_duration=1,
                include_cross_other=False,
            )
            row.evidence = _stem_evidence_records([comparison])
            for evidence in row.evidence:
                evidence.candidate_number = row.candidate_number
                if (
                    evidence.dtw_result == "accepted"
                    and evidence.source_stem == evidence.new_song_stem
                    and evidence.source_stem in LABELS
                ):
                    row.suggested_instruments.append(LABELS[evidence.source_stem])
            row.status = "checked"
            row.reason = (
                f"One representative was compared for {represented} grouped "
                "use(s). "
                + (
                    "Supporting same-stem evidence was found; confirm by listening."
                    if row.suggested_instruments
                    else "No reliable same-stem alignment was found."
                )
            )
        except (StemSeparationUnavailable, OSError, RuntimeError, ValueError) as exc:
            failure_reason = str(exc)
            row.status, row.reason = "failed", failure_reason
            persist()
            break
        count += 1
        persist()

    unfinished = [
        row for row in updated.instrument_occurrences if row.status not in FINAL
    ]
    if unfinished:
        reason = failure_reason or (
            "Integrated group stem analysis did not finish within the available "
            "analysis budget."
        )
        for row in unfinished:
            row.status = "failed"
            row.reason = reason

    updated.stem_evidence = [
        evidence
        for row in updated.instrument_occurrences
        for evidence in row.evidence
    ]
    updated.methods["stems"] = (
        f"demucs_{settings.stem_model_name}_group_representatives; "
        "same-label stem DTW only; one representative per relationship group"
    )
    if any(row.status == "failed" for row in updated.instrument_occurrences):
        warning = (
            "One or more grouped stem comparisons could not finish. Sony and "
            "full-mix DTW timestamp evidence is preserved."
        )
        if warning not in updated.warnings:
            updated.warnings.append(warning)
    persist()
    return updated
