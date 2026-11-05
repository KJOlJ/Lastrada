"""Creator-facing document; uncertain measurements never become confirmed use."""

from html import escape
from lastrada.schemas.models import Analysis, PathResult
from lastrada.reporting.sample_flow import automatic_path

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
        if analysis.review.workflow == "sample" and path.locate.detection_status == "not_requested":
            continue
        if path.locate.detection_status == "not_detected":
            if path.locate.review_required:
                missing.append(f"{name}: check the no-use finding")
            continue
        if path.locate.detection_status != "verified" and not automatic_path(path):
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
        if analysis.review.workflow == "sample" and path.locate.detection_status == "not_requested":
            continue
        lines += [RIGHTS_NAMES[rights]]
        automatic = automatic_path(path)
        if path.locate.detection_status == "verified" or automatic:
            if automatic:
                lines.append("Sample timings are automatically estimated; description reviewed separately.")
            for feature in path.describe.elements:
                if feature.value:
                    lines.append(
                        f"{feature.feature.replace('_', ' ').capitalize()}: {feature.value}"
                    )
            if path.classification.placement == "throughout":
                lines.append("Placement: throughout the track")
                if automatic and any(i.end_review for i in path.locate.sample_occurrences):
                    lines.append("Some endings are uncertain and may extend beyond the estimated times.")
            else:
                for occurrence in path.locate.sample_occurrences:
                    approximate = "≈ " if automatic and occurrence.end_review else ""
                    lines.append(
                        f"In new track: {timestamp(occurrence.new_start)}–{approximate}{timestamp(occurrence.new_end)}; "
                        f"in original: {timestamp(occurrence.original_start)}–{approximate}{timestamp(occurrence.original_end)}"
                    )
                    if approximate:
                        lines.append("The ending is uncertain and may extend beyond the displayed time.")
            if (
                path.locate.total_covered_seconds is not None
                and path.locate.coverage_percentage is not None
            ):
                lines.append(
                    f"{'Estimated' if automatic else 'Reviewed'} total use: {path.locate.total_covered_seconds:.2f}s "
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
        lines.extend(path.describe.limitations)
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
        if analysis.review.workflow == "sample" and path.locate.detection_status == "not_requested":
            continue
        name = "the original recording" if rights == "master" else "the original composition"
        if path.locate.detection_status == "not_detected":
            parts.append(
                "No separate replayed melody or re-sung lyrics were identified in this listening check."
                if rights == "publishing"
                else f"No reuse of {name} was identified in this listening check."
            )
            continue
        automatic = automatic_path(path)
        if path.locate.detection_status != "verified" and not automatic:
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
            parts.append(f"{'Estimated appearances' if automatic else 'It can be heard'} at {ranges} in the new track.")
        if path.describe.sections and path.describe.sections != ["whole track"]:
            parts.append(
                "It appears in the matched passages."
                if path.describe.sections == ["matched passages"]
                else "It appears in the " + ", ".join(path.describe.sections) + " sections."
            )
        if automatic and any(i.end_review for i in path.locate.sample_occurrences):
            parts.append("Some sample endings are uncertain and may extend beyond the estimated times.")
        if path.describe.repetition:
            parts.append(f"Repetition: {path.describe.repetition}.")
        if path.describe.role_in_new_song:
            parts.append(f"Its role in the track: {path.describe.role_in_new_song}.")
    return " ".join(parts)
