from datetime import datetime, timezone
from lastrada.schemas.models import Analysis, PathResult, Review
from lastrada.alignment.intervals import coverage


def reviewed_copy(
    automated: Analysis, paths: dict, text: str, reviewer: str, approve=False, notes="",
    workflow="classic",
):
    from lastrada.reporting.sample_flow import automatic_path, sample_intervals
    if approve and not reviewer.strip():
        raise ValueError("A reviewer name is required for approval")
    corrected = automated.model_copy(deep=True)
    for rights, value in paths.items():
        if rights not in automated.input.analysis_scope:
            raise ValueError("Cannot review an unrequested rights path")
        path = PathResult.model_validate(value)
        if path.rights_type != rights:
            raise ValueError("Rights path mismatch")
        if automatic_path(path):
            if rights != "master" or workflow != "sample" or path.locate.sample_occurrences != sample_intervals(automated):
                raise ValueError("Automatic times must retain supported detector evidence")
        for interval in path.locate.sample_occurrences + path.locate.measurement_intervals:
            if interval.new_end > automated.durations["new"] + 1e-6:
                raise ValueError("Interval exceeds the new recording")
            if (
                interval.original_end is not None
                and interval.original_end > automated.durations["original"] + 1e-6
            ):
                raise ValueError("Source interval exceeds original recording")
        if path.locate.detection_status == "verified":
            if not path.locate.sample_occurrences:
                raise ValueError("Verified reuse needs expert-reviewed occurrences")
            if any(
                i.status != "expert_verified" or i.source != "expert_review"
                for i in path.locate.sample_occurrences
            ):
                raise ValueError(
                    "Verified reuse requires explicitly expert-reviewed interval evidence"
                )
            seconds, percent = coverage(path.locate.sample_occurrences, automated.durations["new"])
            path.locate.total_covered_seconds, path.locate.coverage_percentage = seconds, percent
        setattr(corrected, rights, path)
    if approve:
        for rights in automated.input.analysis_scope:
            path = getattr(corrected, rights)
            if workflow == "sample" and rights != "master" and path.locate.detection_status == "not_requested":
                continue
            if path.locate.detection_status not in ("verified", "not_detected") and not automatic_path(path):
                raise ValueError(f"{rights}: resolve uncertain reuse before approval")
            if path.locate.review_required or path.classification.review_required:
                raise ValueError(f"{rights}: confirm findings and classification before approval")
        if not text.strip():
            raise ValueError("An approved draft must contain a narrative")
    corrected.nature_of_use.text = text
    corrected.nature_of_use.source = "expert_review"
    corrected.nature_of_use.review_required = not approve
    payload = corrected.model_dump(mode="json", exclude={"review"})
    result = automated.model_copy(deep=True)
    result.review = Review(
        workflow=workflow,
        status="approved" if approve else "edited",
        reviewer=reviewer or None,
        reviewed_at=datetime.now(timezone.utc).isoformat(),
        notes=notes,
        corrected=payload,
    )
    return result
