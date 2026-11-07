from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_main_worker_runs_grouped_stems_before_marking_analysis_complete():
    source = (ROOT / "src/lastrada/web/execute.py").read_text()
    sony = source.index("result = analyze_pair")
    grouped_stems = source.index("result = run_occurrence_instruments", sony)
    completed = source.index('status="completed"', grouped_stems)

    assert sony < grouped_stems < completed
    assert "One representative pair is selected per grouped timestamp relationship" in source
    assert "budget_seconds=900" in source


def test_browser_never_launches_a_post_page_load_stem_job():
    source = (ROOT / "web/public/auto-instruments.js").read_text()

    assert ".click()" not in source
    assert "data-action=\"stems\"" in source
    assert "controls.hidden = true" in source
    assert "integratedStemPipeline" in source
