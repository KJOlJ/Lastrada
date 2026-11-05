"""Cloud-independent validation and review rules for the web client."""

import hashlib
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from lastrada.schemas.models import Analysis, Interval, Feature, Placement, PathResult
from lastrada.reporting.review import reviewed_copy
from lastrada.reporting.document import missing_document_inputs, creator_narrative
from lastrada.alignment.intervals import coverage

MAX_UPLOAD_BYTES = 100 * 1024 * 1024


def owner_key(uid):
    return hashlib.sha256(uid.encode()).hexdigest()


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, str_strip_whitespace=True)


class Upload(Payload):
    name: str = Field(min_length=1, max_length=250)
    size: int = Field(gt=0, le=MAX_UPLOAD_BYTES)
    content_type: str = "application/octet-stream"


class Credits(Payload):
    original_title: str = Field(min_length=1, max_length=200)
    original_artist: str = Field(min_length=1, max_length=200)
    new_title: str = Field(min_length=1, max_length=200)
    new_artist: str = Field(min_length=1, max_length=200)


class CreateAnalysis(Payload):
    original: Upload
    new: Upload
    credits: Credits


class UseReview(Payload):
    status: Literal["pending", "no_use", "confirmed"] = "pending"
    intervals: list[Interval] = Field(default_factory=list, max_length=2000)
    times_confirmed: bool = False
    details_confirmed: bool = False
    element: str = Field(default="", max_length=2000)
    lyrics: str = Field(default="", max_length=4000)
    method: str = Field(default="", max_length=2000)
    repetition: str = Field(default="", max_length=2000)
    role: str = Field(default="", max_length=2000)
    sections: list[Literal["whole track", "intro", "verse", "chorus", "bridge", "outro"]] = Field(
        default_factory=list
    )
    placement: Placement | None = None


class ReviewPayload(Payload):
    paths: dict[Literal["master", "publishing"], UseReview]
    narrative: str = Field(default="", max_length=20000)
    reviewer: str = Field(default="", max_length=200)
    notes: str = Field(default="", max_length=4000)
    approve: bool = False


def apply_review(analysis: Analysis, payload: ReviewPayload):
    if set(payload.paths) != set(analysis.input.analysis_scope):
        raise ValueError("Review each applicable type of use")
    paths = {}
    for rights, answer in payload.paths.items():
        path = PathResult(rights_type=rights)
        if answer.status == "no_use":
            path.locate.detection_status = "not_detected"
            path.locate.sample_detected = False
            path.locate.review_required = False
            path.classification.review_required = False
        else:
            confirmed = (
                answer.status == "confirmed" and answer.times_confirmed and bool(answer.intervals)
            )
            path.locate.detection_status = "verified" if confirmed else "candidate"
            path.locate.sample_detected = True if confirmed else None
            path.locate.review_required = not answer.details_confirmed
            path.locate.sample_occurrences = [
                i.model_copy(
                    update={
                        "source": "expert_review"
                        if answer.times_confirmed
                        else "unconfirmed_timing_suggestion",
                        "status": "expert_verified" if answer.times_confirmed else "estimated",
                        "end_review": None if answer.times_confirmed else i.end_review,
                        "ending_review_context": i.ending_review_context or i.end_review,
                    }
                )
                for i in answer.intervals
            ]
            if confirmed:
                seconds, percent = coverage(
                    path.locate.sample_occurrences, analysis.durations["new"]
                )
                path.locate.total_covered_seconds, path.locate.coverage_percentage = (
                    seconds,
                    percent,
                )
            path.describe.elements = (
                [
                    Feature(
                        feature="musical_element",
                        value=answer.element.strip(),
                        source="expert_review"
                        if answer.details_confirmed
                        else "unconfirmed_description",
                        status="expert_verified" if answer.details_confirmed else "estimated",
                        review_required=not answer.details_confirmed,
                    )
                ]
                if answer.element.strip()
                else []
            )
            if answer.lyrics.strip():
                path.describe.elements.append(
                    Feature(
                        feature="lyrics",
                        value=answer.lyrics.strip(),
                        source="expert_review"
                        if answer.details_confirmed
                        else "unconfirmed_description",
                        status="expert_verified" if answer.details_confirmed else "estimated",
                        review_required=not answer.details_confirmed,
                    )
                )
            path.describe.sections = answer.sections
            path.describe.reuse_type = answer.method.strip() or None
            path.describe.repetition = answer.repetition.strip() or None
            path.describe.role_in_new_song = answer.role.strip() or None
            path.classification.placement = answer.placement
            path.classification.source = "expert_review"
            path.classification.review_required = (
                not answer.details_confirmed or answer.placement is None
            )
        paths[rights] = path.model_dump(mode="json")
    candidate = analysis.model_copy(deep=True)
    candidate.review.corrected = None
    for rights, value in paths.items():
        setattr(candidate, rights, PathResult.model_validate(value))
    narrative = payload.narrative.strip() or creator_narrative(candidate)
    if payload.approve:
        missing = missing_document_inputs(candidate)
        if missing:
            raise ValueError("Complete your details: " + "; ".join(missing))
    return reviewed_copy(
        analysis,
        paths,
        narrative,
        payload.reviewer.strip(),
        approve=payload.approve,
        notes=payload.notes,
    )
