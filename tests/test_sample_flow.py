import pytest

from lastrada.reporting.document import document_text, missing_document_inputs
from lastrada.reporting.sample_flow import LYRICS_UNASSESSED, sample_intervals, sample_review
from lastrada.schemas.models import Analysis, Intake, Interval, Placement, Work
from lastrada.web.domain import ReviewPayload, UseReview, apply_review


def analysis_with_match(source="direct_waveform_local_alignment"):
    analysis = Analysis(
        case_id="sample",
        input=Intake(
            case_id="sample",
            original_work=Work(title="Original", artist="Artist"),
            new_work=Work(title="New", artist="Creator"),
            analysis_scope=["master", "publishing"],
        ),
        durations={"new": 100, "original": 80},
    )
    analysis.master.locate.sample_occurrences = [
        Interval(
            new_start=30,
            new_end=31.5,
            original_start=2,
            original_end=3.5,
            source=source,
            status="candidate",
            end_review={"new_through": 32, "original_through": 4},
        )
    ]
    return analysis


def sample_payload(analysis, approve=True):
    proposal = sample_review(analysis)
    return ReviewPayload(
        workflow="sample",
        reviewer="Creator",
        approve=approve,
        paths={
            "master": UseReview(
                status="confirmed",
                details_confirmed=True,
                **proposal["description"],
                sections=proposal["placement"]["values"]["sections"],
                placement=proposal["placement"]["values"]["placement"],
            ),
        },
    )


@pytest.mark.parametrize(
    "source", ["sampleid_rank_sequence", "sampleid_chunk_cosine", "pfnmf_activation"]
)
def test_coarse_or_unpaired_estimates_do_not_skip_into_an_accepted_sample(source):
    analysis = analysis_with_match(source)
    assert sample_review(analysis)["status"] == "not_identified"
    assert sample_intervals(analysis) == []
    with pytest.raises(ValueError, match="No supported recording match"):
        apply_review(
            analysis,
            ReviewPayload(
                workflow="sample",
                paths={
                    "master": UseReview(status="confirmed", details_confirmed=True),
                },
            ),
        )


@pytest.mark.parametrize(
    "source",
    [
        "direct_waveform_local_alignment",
        "dtw_chroma_local_alignment",
        "stem-assisted DTW · guitar → guitar",
    ],
)
def test_supported_localization_prefills_every_answer_without_inventing_identity(source):
    proposal = sample_review(analysis_with_match(source))
    assert proposal["status"] == "identified"
    assert all(proposal["description"].values())
    assert "instrument not identified" in proposal["description"]["element"]
    assert proposal["description"]["lyrics"] == LYRICS_UNASSESSED
    assert proposal["placement"]["values"]["sections"] == ["matched passages"]
    assert "confirm" in proposal["notes"]["role"].lower()


def test_confirming_description_preserves_automated_times_and_exports_without_replay_claims():
    analysis = analysis_with_match()
    before = analysis.model_dump()
    payload = sample_payload(analysis)
    assert payload.paths["master"].times_confirmed is False
    saved = Analysis.model_validate_json(apply_review(analysis, payload).model_dump_json())
    assert saved.review.status == "approved" and saved.review.workflow == "sample"
    path = saved.review.corrected["master"]
    assert path["locate"]["detection_status"] == "candidate"
    assert path["locate"]["timing_source"] == "automated"
    assert path["locate"]["sample_detected"] is None
    assert path["locate"]["sample_occurrences"] == [
        analysis.master.locate.sample_occurrences[0].model_dump(mode="json")
    ]
    assert saved.review.corrected["publishing"]["locate"]["detection_status"] == "not_requested"
    assert missing_document_inputs(saved) == []
    text = document_text(saved)
    assert "automatically estimated" in text and "Estimated total use" in text
    assert "≈ " in text and "ending is uncertain" in text
    assert "Reused lyrics have not been assessed" in text
    assert "No separate replayed" not in text and "Replayed melody" not in text
    assert not any(f["feature"] == "lyrics" for f in path["describe"]["elements"])
    assert analysis.model_dump() == before


def test_description_only_review_cannot_forge_or_confirm_timestamps():
    analysis = analysis_with_match()
    payload = sample_payload(analysis)
    payload.paths["master"].intervals = [Interval(new_start=1, new_end=4, source="browser")]
    with pytest.raises(ValueError, match="must match the stored analysis"):
        apply_review(analysis, payload)
    payload.paths["master"].intervals = []
    payload.paths["master"].times_confirmed = True
    with pytest.raises(ValueError, match="not a listening confirmation"):
        apply_review(analysis, payload)


def test_throughout_description_keeps_ending_uncertainty_in_narrative_and_export():
    analysis = analysis_with_match()
    payload = sample_payload(analysis)
    payload.paths["master"].placement = Placement.THROUGHOUT
    payload.paths["master"].sections = ["whole track"]
    saved = apply_review(analysis, payload)
    assert "endings are uncertain" in saved.review.corrected["nature_of_use"]["text"]
    assert "Some endings are uncertain" in document_text(saved)


def test_description_uses_current_instrument_evidence_and_separates_source_presence():
    from lastrada.separation.occurrences import occurrence_rows
    from lastrada.schemas.models import InstrumentPresence

    analysis = analysis_with_match()
    model = "htdemucs_6s"
    analysis.instrument_occurrences = occurrence_rows(analysis, model)
    row = analysis.instrument_occurrences[0]
    row.status = "checked"
    row.suggested_instruments = ["Guitar"]
    assert sample_review(analysis, model)["description"]["element"] == "Guitar"
    row.context_only = True
    row.source_sounds = [
        InstrumentPresence(
            instrument="Bass",
            energy_share=0.6,
            scope="sample",
            start=2,
            end=3.5,
        )
    ]
    assert (
        sample_review(analysis, model)["description"]["element"]
        == "Sampled passage; source sounds include bass"
    )
    row.source_sounds[0].scope = "context"
    assert "instrument not identified" in sample_review(analysis, model)["description"]["element"]
    row.context_only = False
    row.model_name = "htdemucs"
    assert "instrument not identified" in sample_review(analysis, model)["description"]["element"]
    row.model_name = model
    row.evidence_version = 1
    assert "instrument not identified" in sample_review(analysis, model)["description"]["element"]


def test_description_confirmation_remains_explicit_and_saved_edits_survive_reload():
    analysis = analysis_with_match()
    payload = sample_payload(analysis)
    payload.paths["master"].details_confirmed = False
    with pytest.raises(ValueError, match="confirm findings"):
        apply_review(analysis, payload)
    payload.approve = False
    payload.paths["master"].element = "My own sound description"
    payload.paths["master"].lyrics = ""
    saved = Analysis.model_validate_json(apply_review(analysis, payload).model_dump_json())
    assert saved.review.description_answers["element"] == "My own sound description"
    assert saved.review.description_answers["lyrics"] == ""
    assert saved.master == analysis.master


def test_earlier_explicit_timing_and_publishing_review_are_preserved():
    analysis = analysis_with_match()
    answer = UseReview(
        status="confirmed",
        times_confirmed=True,
        details_confirmed=True,
        intervals=[
            Interval(new_start=33, new_end=36, original_start=5, original_end=8, source="browser")
        ],
        element="Bass",
        method="Sampled",
        repetition="Once",
        role="Accent",
        sections=["verse"],
        placement="one_time",
    )
    old = apply_review(
        analysis,
        ReviewPayload(
            paths={
                "master": answer,
                "publishing": UseReview(status="no_use"),
            },
            reviewer="Creator",
            approve=True,
        ),
    )
    old = Analysis.model_validate_json(old.model_dump_json())
    assert sample_intervals(old)[0].new_start == 33
    new = apply_review(old, sample_payload(old))
    assert new.review.corrected["master"]["locate"]["detection_status"] == "verified"
    assert new.review.corrected["master"]["locate"]["timing_source"] == "reviewed"
    assert new.review.corrected["publishing"] == old.review.corrected["publishing"]
    assert new.master == analysis.master
