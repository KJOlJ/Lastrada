import pytest
from lastrada.audio.synthetic import demo_pair
from lastrada.pipeline import analyze_pair
from lastrada.schemas.models import Intake, Work, Interval
from lastrada.web.domain import ReviewPayload, UseReview, apply_review, owner_key, Upload
from lastrada.reporting.document import missing_document_inputs, document_text


@pytest.fixture
def example():
    original, new, _ = demo_pair()
    intake = Intake(
        case_id="web",
        original_work=Work(title="Source", artist="Test"),
        new_work=Work(title="Mix", artist="Test"),
        analysis_scope=["master", "publishing"],
    )
    return analyze_pair(intake, original, new, synthetic=True)


def complete():
    return UseReview(
        status="confirmed",
        times_confirmed=True,
        details_confirmed=True,
        intervals=[Interval(new_start=1, new_end=3, source="browser")],
        element="Bassline",
        method="Looped recording",
        repetition="Repeats throughout",
        role="Main hook",
        sections=["whole track"],
        placement="throughout",
    )


def test_web_review_and_throughout_export_preserve_automated_evidence(example):
    before = example.model_dump()
    payload = ReviewPayload(
        paths={"master": complete(), "publishing": UseReview(status="no_use")},
        reviewer="Creator",
        approve=True,
    )
    reviewed = apply_review(example, payload)
    assert reviewed.review.status == "approved"
    assert missing_document_inputs(reviewed) == []
    assert "throughout the track" in document_text(reviewed)
    assert "0:01.00" not in document_text(reviewed)
    assert example.model_dump() == before


def test_web_cannot_approve_guessed_or_out_of_range_times(example):
    answer = complete()
    answer.times_confirmed = False
    with pytest.raises(ValueError):
        apply_review(
            example,
            ReviewPayload(
                paths={"master": answer, "publishing": UseReview(status="no_use")},
                reviewer="Test",
                approve=True,
            ),
        )
    answer = complete()
    answer.intervals[0].new_end = 1000
    with pytest.raises(ValueError):
        apply_review(
            example,
            ReviewPayload(
                paths={"master": answer, "publishing": UseReview(status="no_use")},
                reviewer="Test",
                approve=True,
            ),
        )


def test_web_private_keys_and_upload_limits():
    assert "/" not in owner_key("../user")
    assert len(owner_key("user")) == 64
    with pytest.raises(ValueError):
        Upload(name="too-big.mp3", size=101 * 1024 * 1024)


def test_unconfirmed_description_prefill_is_not_marked_expert_verified(example):
    answer = complete()
    answer.details_confirmed = False
    payload = ReviewPayload(paths={"master": answer, "publishing": UseReview(status="no_use")})
    reviewed = apply_review(example, payload)
    features = reviewed.review.corrected["master"]["describe"]["elements"]
    assert features[0]["status"] == "estimated"
    assert features[0]["review_required"] is True
    payload.approve = True
    payload.reviewer = "Test"
    with pytest.raises(ValueError):
        apply_review(example, payload)
