"""Timing-only suggestions. Musical identity and looping require creator confirmation."""

from dataclasses import dataclass
from statistics import median
from lastrada.alignment.intervals import merge_ranges
from lastrada.schemas.models import PathResult


@dataclass
class TimingSuggestion:
    kind: str
    question: str
    source: str


def suggested_intervals(analysis, rights):
    if analysis.review.corrected and rights in analysis.review.corrected:
        return list(
            PathResult.model_validate(analysis.review.corrected[rights]).locate.sample_occurrences
        )
    path = getattr(analysis, rights)
    if rights == "publishing":
        return list(path.locate.sample_occurrences)
    return list(path.locate.sample_occurrences or path.locate.measurement_intervals)


def timing_questions(intervals, duration):
    if not intervals or not duration:
        return []
    ranges = merge_ranges([(i.new_start, i.new_end) for i in intervals], duration)
    used = sum(e - s for s, e in ranges)
    spread = (ranges[-1][1] - ranges[0][0]) / duration
    lengths = [e - s for s, e in ranges]
    result = []
    if used / duration >= 0.6 and spread >= 0.85:
        result.append(
            TimingSuggestion(
                "throughout",
                "These estimates are spread across most of your track. Does the sample repeat throughout?",
                "estimated_timing_pattern",
            )
        )
        result.append(
            TimingSuggestion(
                "melody",
                "Does this sampled part carry the melody?",
                "creator_confirmation_required",
            )
        )
    if (
        len(ranges) >= 2
        and median(lengths) <= 8
        and max(lengths) - min(lengths) <= max(0.5, median(lengths) * 0.3)
    ):
        result.append(
            TimingSuggestion(
                "loop",
                "Several estimated moments are short and similar in length. Are they a repeating loop?",
                "estimated_timing_pattern",
            )
        )
    elif len(ranges) == 1 and lengths[0] <= 10:
        result.append(
            TimingSuggestion(
                "one_time",
                "We estimated one short moment. Is the sample used just once?",
                "estimated_timing_pattern",
            )
        )
    return result


def confirmed_prefills(kind, rights):
    # Applied only after an explicit Yes and button click; never overwrite existing edits.
    return {
        "throughout": {"placement": "throughout", "repetition": "Repeated throughout the track"},
        "melody": {
            "element": "a sampled melody" if rights == "master" else "a replayed melody",
            "role": "Carries the melody of the new track",
        },
        "loop": {"repetition": "A short loop repeated in the track"},
        "one_time": {"placement": "one_time", "repetition": "Used once"},
    }.get(kind, {})


@dataclass
class PlacementProposal:
    values: dict
    reason: str
    tentative_sections: bool = False


def placement_proposal(intervals, duration, section_ranges=()):
    """Cheap timing rules. Interior section names are proposals, never detections."""
    if not intervals or not duration or duration <= 0:
        return PlacementProposal({}, "No usable timestamps yet.")
    ranges = merge_ranges([(i.new_start, i.new_end) for i in intervals], duration)
    if not ranges:
        return PlacementProposal({}, "No usable timestamps yet.")
    used = sum(end - start for start, end in ranges)
    span = (ranges[-1][1] - ranges[0][0]) / duration
    lengths = [end - start for start, end in ranges]
    gaps = [right[0] - left[1] for left, right in zip(ranges, ranges[1:])]
    values = {}
    mapped_sections = []
    mapped_coverage = []
    for section in section_ranges:
        label, start, end = section["section"], float(section["start"]), float(section["end"])
        if (
            label not in {"intro", "verse", "chorus", "bridge", "outro"}
            or not 0 <= start < end <= duration
        ):
            raise ValueError("Song-section ranges need a valid name and times within the track")
        hits = [(max(start, a), min(end, b)) for a, b in ranges if min(end, b) > max(start, a)]
        if hits:
            if label not in mapped_sections:
                mapped_sections.append(label)
            mapped_coverage.extend(hits)
    if len(ranges) > 1:
        values["repetition"] = "Recurs in multiple passages"
        if median(lengths) <= 8 and max(lengths) - min(lengths) <= max(0.5, median(lengths) * 0.3):
            values["repetition"] = "A short loop repeated in the track"
    else:
        values["repetition"] = "One continuous appearance"
    if span >= 0.85 and (
        used / duration >= 0.6 or (len(ranges) >= 6 and max(gaps, default=0) <= duration * 0.18)
    ):
        values.update(placement="throughout", sections=["whole track"])
        return PlacementProposal(
            values,
            "Occurrences span most of the track with substantial coverage or frequent repetition.",
        )
    if mapped_sections:
        values["sections"] = mapped_sections
        covered = sum(b - a for a, b in merge_ranges(mapped_coverage, duration))
        if covered >= used - 1e-6:
            from lastrada.classification.placement import classify

            placement = classify(0.0, intervals, mapped_sections, expert=True).placement
            if placement:
                values["placement"] = placement.value
        return PlacementProposal(
            values,
            "Matched sample timestamps to your song-section map. Only labeled overlaps are included; check any unlabeled passages.",
        )
    if ranges[-1][1] <= duration * 0.2:
        values.update(placement="intro_only", sections=["intro"])
        return PlacementProposal(
            values, "All occurrences are in the opening 20%; check that this is your intro.", True
        )
    if ranges[0][0] >= duration * 0.8:
        values.update(placement="outro_only", sections=["outro"])
        return PlacementProposal(
            values, "All occurrences are in the final 20%; check that this is your outro.", True
        )
    if all(end <= duration * 0.2 or start >= duration * 0.8 for start, end in ranges):
        values.update(placement="intro_outro_without_chorus", sections=["intro", "outro"])
        return PlacementProposal(
            values,
            "Occurrences are confined to the opening and ending; check the section names.",
            True,
        )
    if len(ranges) >= 2:
        return PlacementProposal(
            values,
            "Recurring interior passages: timestamps cannot distinguish choruses from verses. Choose the section below, or add its time ranges once in the song-section map.",
            True,
        )
    values["placement"] = "one_time"
    return PlacementProposal(
        values,
        "One interior appearance. Name its verse, chorus or bridge below, or add its time range to the song-section map.",
        True,
    )


def timing_prefills(state, prefix, intervals, duration, rights, section_ranges=()):
    """Update suggested fields without overwriting creator edits or marking reviewed."""
    try:
        proposal = placement_proposal(intervals, duration, section_ranges)
    except (ValueError, TypeError):
        proposal = PlacementProposal(
            {}, "Fix the invalid timestamp or song-section range before applying suggestions."
        )
    values = dict(proposal.values)
    if intervals:
        values["method"] = (
            "Sampled the original recording"
            if rights == "master"
            else "Replayed or re-sang the original music"
        )
    previous = state.get(prefix + "timing_defaults", {})
    if not state.get(prefix + "checked"):
        for field in list(previous):
            if field not in values and state.get(prefix + field) == previous[field]:
                state[prefix + field] = (
                    [] if field == "sections" else "Needs review" if field == "placement" else ""
                )
                previous.pop(field)
        for field, value in values.items():
            current = state.get(prefix + field)
            if (
                current in (None, "", "Needs review")
                or current == []
                or (field in previous and current == previous[field])
            ):
                state[prefix + field] = value
                previous[field] = value
    state[prefix + "timing_defaults"] = previous
    return proposal
