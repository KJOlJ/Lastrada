import pytest
from pydantic import ValidationError
from lastrada.audio.synthetic import demo_pair
from lastrada.pipeline import analyze_pair
from lastrada.schemas.models import Locate, Feature, Interval
from lastrada.reporting.review import reviewed_copy
from lastrada.reporting.export import html_report, json_report
from lastrada.synthesis.narrative import draft
from lastrada.classification.placement import classify
from lastrada.recognition.sampleid_adapter import SampleIDUnavailable


@pytest.fixture
def analysis(intake):
    return analyze_pair(intake, *demo_pair()[:2], synthetic=True)


def test_rights_isolation_and_no_detection_from_pfnmf(analysis):
    assert analysis.master.locate.coverage_percentage > 0
    assert analysis.master.locate.sample_detected is None
    assert analysis.master.locate.detection_status == "not_verified"
    assert analysis.publishing.locate.sample_occurrences == []
    assert analysis.publishing.locate.coverage_percentage is None
    assert analysis.publishing.classification.placement is None


def test_positive_claim_needs_verified_state():
    with pytest.raises(ValidationError):
        Locate(detection_status="candidate", sample_detected=True)


def test_unavailable_model_never_fabricates_matches(intake):
    class Unavailable:
        def match(self, *args, **kwargs):
            raise SampleIDUnavailable("missing checkpoint")

    result = analyze_pair(intake, *demo_pair()[:2], adapter=Unavailable())
    assert result.master.locate.sample_occurrences == []
    assert result.master.locate.detection_status == "not_verified"
    assert "missing checkpoint" in result.warnings


def test_candidate_not_probability(intake):
    class Adapter:
        def match(self, *args, **kwargs):
            return [
                Interval(
                    new_start=2,
                    new_end=4,
                    original_start=0,
                    original_end=2,
                    source="test",
                    status="candidate",
                    similarity=0.99,
                )
            ]

    result = analyze_pair(intake, *demo_pair()[:2], adapter=Adapter())
    assert result.master.locate.detection_status == "candidate"
    assert result.master.locate.sample_detected is None


@pytest.mark.parametrize("chunk_seconds,refined", [(1, False), (5, True)])
def test_direct_search_respects_embedding_window_uncertainty(intake, chunk_seconds, refined):
    import numpy as np
    from lastrada.audio.io import Audio
    from lastrada.config import Settings

    sr = 8000
    source = np.random.default_rng(480).normal(0, 0.2, 4 * sr).astype(np.float32)
    target = np.zeros(12 * sr, dtype=np.float32)
    target[int(2.75 * sr) : int(6.75 * sr)] = source
    coarse = Interval(
        new_start=0,
        new_end=10,
        original_start=0,
        original_end=4,
        source="sampleid_rank_sequence",
        status="candidate",
    )

    class Adapter:
        def match(self, *args, **kwargs):
            return [coarse]

    result = analyze_pair(
        intake,
        Audio(source, sr, 4),
        Audio(target, sr, 12),
        adapter=Adapter(),
        settings=Settings(sampleid_chunk_seconds=chunk_seconds, dtw_enabled=False, iterations=10),
    )
    interval = result.master.locate.sample_occurrences[0]
    if refined:
        assert interval.source == "direct_waveform_local_alignment"
        assert (interval.new_start, interval.new_end) == pytest.approx((2.75, 6.75))
    else:
        assert interval == coarse
    assert result.master.locate.sample_detected is None


def test_placement_abstains_without_sections():
    result = classify(25, [Interval(new_start=1, new_end=2, source="test")])
    assert result.placement is None
    assert result.coverage_category == "25_percent_or_less"


def test_throughout_is_review_required_not_literal_entire():
    result = classify(96, [Interval(new_start=0, new_end=96, source="test")])
    assert result.placement == "throughout"
    assert result.coverage_category == "more_than_25_percent"
    assert result.review_required


def test_review_preserves_original_predictions(analysis):
    path = analysis.publishing.model_copy(deep=True)
    path.locate.detection_status = "verified"
    path.locate.sample_detected = True
    path.locate.sample_occurrences = [
        Interval(new_start=2, new_end=4, source="expert_review", status="expert_verified")
    ]
    path.describe.elements = [
        Feature(
            feature="musical_element",
            value="replayed melody",
            source="expert_review",
            status="expert_verified",
        )
    ]
    revised = reviewed_copy(
        analysis, {"publishing": path.model_dump()}, "Reviewed narrative", "Reviewer"
    )
    assert revised.publishing.locate.detection_status == "not_verified"
    assert revised.review.corrected["publishing"]["locate"]["total_covered_seconds"] == 2
    assert analysis.review.corrected is None
    assert revised.review.status == "edited"


def test_review_out_of_range_rejected(analysis):
    path = analysis.master.model_copy(deep=True)
    path.locate.sample_occurrences = [
        Interval(new_start=2, new_end=100, source="expert_review", status="expert_verified")
    ]
    with pytest.raises(ValueError, match="exceeds"):
        reviewed_copy(analysis, {"master": path.model_dump()}, "text", "Reviewer")


def test_unresolved_approval_rejected(analysis):
    with pytest.raises(ValueError, match="resolve uncertain"):
        reviewed_copy(analysis, {}, "text", "Reviewer", approve=True)


def test_narrative_does_not_invent_instruments_or_source_timestamps(analysis):
    text = draft(analysis).text
    assert "saxophone" not in text
    assert "not verified sample coverage" in text
    assert "compositional reuse has not been localized" in text


def test_export_html_escaping(analysis):
    analysis.case_id = "<script>alert(1)</script>"
    assert "<script>" not in html_report(analysis)
    assert "&lt;script&gt;" in html_report(analysis)
    assert "synthetic-test" in json_report(analysis)


def test_valid_expert_approval_preserves_automated_version(analysis):
    paths = {}
    for rights in analysis.input.analysis_scope:
        path = getattr(analysis, rights).model_copy(deep=True)
        path.locate.detection_status = "verified"
        path.locate.sample_detected = True
        path.locate.sample_occurrences = [
            Interval(new_start=2, new_end=4, source="expert_review", status="expert_verified")
        ]
        path.locate.review_required = False
        path.classification = classify(
            100 * 2 / 12, path.locate.sample_occurrences, ["chorus"], expert=True
        )
        path.classification.review_required = False
        paths[rights] = path.model_dump()
    reviewed = reviewed_copy(
        analysis, paths, "Expert-approved synthetic description", "Reviewer", approve=True
    )
    assert reviewed.review.status == "approved"
    assert reviewed.review.corrected["master"]["locate"]["total_covered_seconds"] == 2
    assert reviewed.master.locate.sample_detected is None


def test_not_detected_cannot_hold_occurrences():
    with pytest.raises(ValidationError):
        Locate(
            detection_status="not_detected",
            sample_detected=False,
            sample_occurrences=[Interval(new_start=0, new_end=1, source="candidate")],
        )
