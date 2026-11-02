"""Creator-facing document; uncertain measurements never become confirmed use."""

from html import escape
from lastrada.schemas.models import Analysis, PathResult

RIGHTS_NAMES = {
    "master": "Recording sample (master)",
    "publishing": "Replayed melody or lyrics (publishing)",
}


def document_paths(analysis):
    source = analysis.review.corrected or analysis.model_dump(mode="json")
    return {r: PathResult.model_validate(source[r]) for r in analysis.input.analysis_scope}


def missing_document_inputs(analysis):
    missing = []
    for rights, path in document_paths(analysis).items():
        name = RIGHTS_NAMES[rights]
        if path.locate.detection_status == "not_detected":
            if path.locate.review_required:
                missing.append(f"{name}: check the no-use finding")
            continue
        if path.locate.detection_status != "verified":
            missing.append(f"{name}: confirm what was reused")
        if not path.locate.sample_occurrences:
            missing.append(f"{name}: add the times it appears in your track")
        if not any(f.feature == "musical_element" and f.value for f in path.describe.elements):
            missing.append(f"{name}: identify the sampled sound or musical part")
        if not path.describe.sections:
            missing.append(f"{name}: name the song sections")
        if not path.classification.placement:
            missing.append(f"{name}: choose where it appears overall")
        for field, message in [
            ("reuse_type", "describe how you used it"),
            ("repetition", "describe repetition or looping"),
            ("role_in_new_song", "describe its role in your track"),
        ]:
            if not getattr(path.describe, field):
                missing.append(f"{name}: {message}")
    return missing


def timestamp(value):
    return "not provided" if value is None else f"{int(value) // 60}:{value % 60:05.2f}"


def document_text(analysis: Analysis):
    data = analysis.review.corrected or analysis.model_dump(mode="json")
    state = "Reviewed" if analysis.review.status == "approved" else "Draft — review required"
    lines = [
        "NATURE OF USE",
        state,
        "",
        f"Case: {analysis.case_id}",
        f"New track: {analysis.input.new_work.title} — {analysis.input.new_work.artist}",
        f"Original track: {analysis.input.original_work.title} — {analysis.input.original_work.artist}",
        "",
        "Description of use",
        data["nature_of_use"]["text"],
        "",
    ]
    for rights, path in document_paths(analysis).items():
        lines += [RIGHTS_NAMES[rights]]
        if path.locate.detection_status == "verified":
            for feature in path.describe.elements:
                if feature.value:
                    lines.append(
                        f"{feature.feature.replace('_', ' ').capitalize()}: {feature.value}"
                    )
            if path.classification.placement == "throughout":
                lines.append("Placement: throughout the track")
            else:
                for occurrence in path.locate.sample_occurrences:
                    lines.append(
                        f"In new track: {timestamp(occurrence.new_start)}–{timestamp(occurrence.new_end)}; "
                        f"in original: {timestamp(occurrence.original_start)}–{timestamp(occurrence.original_end)}"
                    )
            if (
                path.locate.total_covered_seconds is not None
                and path.locate.coverage_percentage is not None
            ):
                lines.append(
                    f"Reviewed total use: {path.locate.total_covered_seconds:.2f}s "
                    f"({path.locate.coverage_percentage:.1f}% of the new track)"
                )
            else:
                lines.append("Total duration of use: not yet confirmed")
        elif path.locate.detection_status == "not_detected":
            lines.append("No reuse identified in this rights path; this is not a legal conclusion.")
        else:
            lines.append("Use has not been confirmed. Automated matching needs listening review.")
        for label, value in [
            ("Sections", ", ".join(path.describe.sections)),
            ("How used", path.describe.reuse_type),
            ("Repetition", path.describe.repetition),
            ("Role in the track", path.describe.role_in_new_song),
        ]:
            lines.append(f"{label}: {value or 'not yet provided'}")
        lines.append("")
    missing = missing_document_inputs(analysis)
    if missing:
        lines += (
            ["Still needed to complete this document"] + [f"• {item}" for item in missing] + [""]
        )
    if analysis.review.reviewer:
        lines.append(f"Reviewed by: {analysis.review.reviewer}")
    if analysis.review.notes:
        lines.append(f"Review notes: {analysis.review.notes}")
    lines += [
        "",
        "This document describes musical use. It is not a license or a clearance decision.",
    ]
    return "\n".join(lines)


def document_html(analysis):
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Nature of Use</title>'
        "<style>body{font:16px system-ui;max-width:850px;margin:50px auto;padding:24px;color:#271d36}"
        "pre{font:inherit;white-space:pre-wrap;line-height:1.7}@media print{body{margin:0}}</style>"
        f"</head><body><pre>{escape(document_text(analysis))}</pre></body></html>"
    )


def creator_narrative(analysis):
    parts = []
    for rights in analysis.input.analysis_scope:
        path = getattr(analysis, rights)
        name = "the original recording" if rights == "master" else "the original composition"
        if path.locate.detection_status == "not_detected":
            parts.append(
                "No separate replayed melody or re-sung lyrics were identified in this listening check."
                if rights == "publishing"
                else f"No reuse of {name} was identified in this listening check."
            )
            continue
        if path.locate.detection_status != "verified":
            parts.append(
                f"The use of {name} in the new track has not yet been checked. "
                "The musical part, its appearances and the way it is used still need to be described."
            )
            continue
        element = next(
            (
                str(f.value)
                for f in path.describe.elements
                if f.feature == "musical_element" and f.value
            ),
            "a musical part not yet identified",
        )
        parts.append(f"The new track uses {element} from {name}.")
        if path.describe.reuse_type:
            parts.append(f"How it is used: {path.describe.reuse_type}.")
        if path.classification.placement == "throughout":
            parts.append("It can be heard throughout the track.")
        elif path.locate.sample_occurrences:
            ranges = ", ".join(
                f"{timestamp(i.new_start)}–{timestamp(i.new_end)}"
                for i in path.locate.sample_occurrences
            )
            parts.append(f"It can be heard at {ranges} in the new track.")
        if path.describe.sections and path.describe.sections != ["whole track"]:
            parts.append("It appears in the " + ", ".join(path.describe.sections) + " sections.")
        if path.describe.repetition:
            parts.append(f"Repetition: {path.describe.repetition}.")
        if path.describe.role_in_new_song:
            parts.append(f"Its role in the track: {path.describe.role_in_new_song}.")
    return " ".join(parts)
