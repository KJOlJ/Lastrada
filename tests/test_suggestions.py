from lastrada.reporting.suggestions import timing_questions, suggested_intervals, confirmed_prefills
from lastrada.schemas.models import Analysis, Intake, Work, Interval


def intervals(ranges):
    return [Interval(new_start=s, new_end=e, source="pfnmf_activation") for s, e in ranges]


def test_distributed_timing_asks_questions_not_assertions():
    questions = timing_questions(intervals([(0, 30), (40, 70), (80, 100)]), 100)
    assert {q.kind for q in questions} == {"throughout", "melody"}
    assert all(q.question.endswith("?") for q in questions)


def test_short_regular_regions_only_suggest_a_loop():
    questions = timing_questions(intervals([(1, 5), (21, 25), (41, 45)]), 100)
    assert [q.kind for q in questions] == ["loop"]
    assert "times" not in confirmed_prefills("loop", "master")["repetition"]


def test_single_short_region_asks_about_one_time_use():
    assert timing_questions(intervals([(12, 16)]), 100)[0].kind == "one_time"


def test_measurements_are_not_copied_into_publishing():
    intake = Intake(
        case_id="synthetic",
        original_work=Work(title="Source", artist="Generated"),
        new_work=Work(title="Mix", artist="Generated"),
        analysis_scope=["master", "publishing"],
    )
    result = Analysis(case_id="synthetic", input=intake)
    result.master.locate.measurement_intervals = intervals([(2, 4)])
    assert suggested_intervals(result, "master")[0].source == "pfnmf_activation"
    assert suggested_intervals(result, "publishing") == []
    assert result.master.locate.sample_detected is None


def test_timing_rules_prefill_temporal_placement_without_guessing_verse_or_chorus():
    from lastrada.reporting.suggestions import placement_proposal

    assert placement_proposal(intervals([(0, 8)]), 100).values["placement"] == "intro_only"
    assert placement_proposal(intervals([(92, 100)]), 100).values["placement"] == "outro_only"
    assert placement_proposal(intervals([(0, 8), (94, 99)]), 100).values["sections"] == [
        "intro",
        "outro",
    ]
    assert placement_proposal(intervals([(0, 30), (40, 70), (80, 100)]), 100).values[
        "sections"
    ] == ["whole track"]
    repeated = placement_proposal(intervals([(24, 28), (54, 58)]), 100)
    assert repeated.values["repetition"] == "A short loop repeated in the track"
    assert "sections" not in repeated.values and "placement" not in repeated.values
    assert repeated.tentative_sections


def test_section_map_classifies_actual_overlapping_sections():
    from lastrada.reporting.suggestions import placement_proposal

    samples = intervals([(24, 28), (54, 58)])
    chorus_map = [
        {"section": "chorus", "start": 20, "end": 30},
        {"section": "chorus", "start": 50, "end": 60},
    ]
    assert placement_proposal(samples, 100, chorus_map).values["placement"] == "chorus_only"
    verse_map = [dict(row, section="verse") for row in chorus_map]
    assert placement_proposal(samples, 100, verse_map).values["placement"] == "verses"
    bridge_map = [{"section": "bridge", "start": 60, "end": 80}]
    assert (
        placement_proposal(intervals([(62, 75)]), 100, bridge_map).values["placement"]
        == "bridge_only"
    )
    mixed_map = [chorus_map[0], dict(chorus_map[1], section="verse")]
    assert placement_proposal(samples, 100, mixed_map).values["placement"] == "selected_sections"
    partial = placement_proposal(samples, 100, chorus_map[:1])
    assert "placement" not in partial.values


def test_prefills_keep_creator_edits_and_never_confirm_evidence():
    from lastrada.reporting.suggestions import timing_prefills

    state = {"review_master_role": "Main hook"}
    timing_prefills(
        state, "review_master_", intervals([(0, 30), (40, 70), (80, 100)]), 100, "master"
    )
    assert state["review_master_placement"] == "throughout"
    assert state["review_master_method"] == "Sampled the original recording"
    assert not state.get("review_master_checked")
    assert not state.get("review_master_times_confirmed")
    state["review_master_repetition"] = "My own description"
    timing_prefills(state, "review_master_", intervals([(92, 100)]), 100, "master")
    assert state["review_master_placement"] == "outro_only"
    assert state["review_master_repetition"] == "My own description"
    assert state["review_master_role"] == "Main hook"


def test_new_timing_pattern_clears_stale_automatic_sections_and_invalid_rows_do_not_crash():
    from lastrada.reporting.suggestions import timing_prefills

    state = {}
    timing_prefills(state, "review_master_", intervals([(0, 95)]), 100, "master")
    assert state["review_master_placement"] == "throughout"
    timing_prefills(state, "review_master_", intervals([(30, 33), (60, 63)]), 100, "master")
    assert state["review_master_placement"] == "Needs review"
    assert state["review_master_sections"] == []
    proposal = timing_prefills(state, "review_master_", intervals([(30, 130)]), 100, "master")
    assert "invalid" in proposal.reason
