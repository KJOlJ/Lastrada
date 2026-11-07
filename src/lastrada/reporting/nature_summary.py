"""Deterministic master-sample summary derived from timestamps and stem evidence."""

from __future__ import annotations

from collections import defaultdict
from statistics import median

from lastrada.alignment.intervals import merge_ranges
from lastrada.reporting.suggestions import placement_proposal, suggested_intervals
from lastrada.schemas.models import Analysis


def _accepted_stem_matches(analysis: Analysis):
    grouped = defaultdict(lambda: {"groups": {}, "ratios": []})
    try:
        from lastrada.separation.occurrences import relationship_groups

        group_counts = {
            group.group_id: len(group.occurrences)
            for group in relationship_groups(analysis)
        }
    except (ImportError, TypeError, ValueError):
        group_counts = {}

    def add(evidence, group_key, represented_uses=1):
        source = str(evidence.source_stem).lower()
        derivative = str(evidence.new_song_stem).lower()
        if (
            evidence.dtw_result != "accepted"
            or source != derivative
            or source == "full_mix"
        ):
            return
        grouped[source]["groups"][group_key] = max(
            grouped[source]["groups"].get(group_key, 0),
            max(1, int(represented_uses)),
        )
        if evidence.duration_ratio is not None:
            grouped[source]["ratios"].append(float(evidence.duration_ratio))

    for index, row in enumerate(analysis.instrument_occurrences):
        group_key = row.occurrence_id or f"group-{index + 1}"
        represented_uses = group_counts.get(group_key, 1)
        for evidence in row.evidence:
            add(evidence, group_key, represented_uses)

    if not grouped:
        for index, evidence in enumerate(analysis.stem_evidence):
            add(evidence, f"candidate-{evidence.candidate_number or index + 1}")

    result = []
    for stem, values in grouped.items():
        ratios = values["ratios"]
        result.append(
            {
                "stem": stem,
                "moment_count": sum(values["groups"].values()),
                "duration_ratio": median(ratios) if ratios else None,
            }
        )
    result.sort(key=lambda item: (-item["moment_count"], item["stem"]))
    return result


def _source_ranges(intervals):
    pairs = [
        (interval.original_start, interval.original_end)
        for interval in intervals
        if interval.original_start is not None and interval.original_end is not None
    ]
    return merge_ranges(pairs) if pairs else []


def nature_of_use_summary(analysis: Analysis):
    """Return an editable, non-legal master-sample summary for the web review page."""
    if "master" not in analysis.input.analysis_scope:
        return None

    intervals = suggested_intervals(analysis, "master")
    duration = float(analysis.durations.get("new", 0) or 0)
    ranges = (
        merge_ranges([(item.new_start, item.new_end) for item in intervals], duration)
        if intervals and duration > 0
        else []
    )
    covered = sum(end - start for start, end in ranges)
    percent = 100 * covered / duration if duration > 0 else 0.0
    proposal = placement_proposal(intervals, duration) if duration > 0 else None
    values = dict(proposal.values) if proposal else {}
    repetition = values.get("repetition")

    if values.get("placement") == "throughout":
        sampling_type = "throughout"
        sampling_label = "Repeated throughout the track"
    elif len(ranges) == 1:
        sampling_type = "one_off"
        sampling_label = "One-off use"
    elif repetition == "A short loop repeated in the track":
        sampling_type = "looped"
        sampling_label = repetition
    elif ranges:
        sampling_type = "repeated"
        sampling_label = "Repeated in multiple passages"
    else:
        sampling_type = "unconfirmed"
        sampling_label = "Timing unconfirmed"

    placement = values.get("placement")
    sections = values.get("sections")
    placement_basis = proposal.reason if proposal else "No usable timestamps yet."
    if not placement and sampling_type == "looped":
        placement = "chorus_only"
        sections = ["chorus"]
        placement_basis = (
            "Recurring similar-length interior uses are provisionally labeled "
            "chorus-like and remain editable."
        )
    elif not placement and len(ranges) > 1:
        placement = "selected_sections"
        sections = None
    elif not placement and len(ranges) == 1:
        placement = "one_time"
        sections = None

    stem_matches = _accepted_stem_matches(analysis)
    stems = [item["stem"] for item in stem_matches]
    element = (
        f"{', '.join(stem.replace('_', ' ') for stem in stems)} "
        f"{'stem' if len(stems) == 1 else 'stems'}"
        if stems
        else "sampled material"
    )
    role = (
        "Recurring foundation in the derivative track"
        if placement == "throughout"
        else "Recurring section element"
        if len(ranges) > 1
        else "Supporting sampled element"
    )

    return {
        "rights_assumption": "master_recording_sample",
        "distinct_uses": len(ranges),
        "covered_seconds": covered,
        "coverage_percentage": percent,
        "first_use": ranges[0][0] if ranges else None,
        "last_use": ranges[-1][1] if ranges else None,
        "merged_derivative_ranges": [list(item) for item in ranges],
        "source_passages": [list(item) for item in _source_ranges(intervals)],
        "sampling_type": sampling_type,
        "sampling_label": sampling_label,
        "placement": placement,
        "sections": sections,
        "placement_basis": placement_basis,
        "stem_matches": stem_matches,
        "sampled_stems": stems,
        "element_suggestion": element,
        "role_suggestion": role,
        "review_required": True,
    }
