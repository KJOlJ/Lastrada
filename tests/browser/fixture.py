"""Generated case for the browser contract test; no client recordings or models."""

import json
import os
from pathlib import Path
import sys
from lastrada.schemas.models import Analysis, Intake, Work, Interval
from lastrada.reporting.suggestions import suggested_intervals, placement_proposal
from lastrada.web.domain import ReviewPayload, apply_review
from lastrada.reporting.document import document_html, document_text
from lastrada.separation.occurrences import occurrence_rows, instrument_prefill
from lastrada.reporting.loop_groups import group_loop_families, loop_family_rows
from lastrada.web.profile import PROFILE


def initial():
    intake = Intake(
        case_id="00000000-0000-4000-8000-000000000001",
        original_work=Work(title="Source", artist="Artist"),
        new_work=Work(title="New", artist="Artist"),
        analysis_scope=["master", "publishing"],
    )
    analysis = Analysis(case_id=intake.case_id, input=intake, durations={"original": 20, "new": 20})
    analysis.master.locate.measurement_intervals = [
        Interval(new_start=1, new_end=4, source="pfnmf")
    ]
    if os.getenv("LASTRADA_BROWSER_ENDING"):
        analysis.master.locate.sample_occurrences = [
            Interval(
                new_start=1, new_end=2.5, original_start=2, original_end=3.5,
                source="direct_waveform_local_alignment", status="candidate",
                end_review={"new_through": 3, "original_through": 4},
            )
        ]
    if os.getenv("LASTRADA_BROWSER_ANALYSIS"):
        analysis = Analysis.model_validate_json(
            Path(os.environ["LASTRADA_BROWSER_ANALYSIS"]).read_text()
        )
        intake = analysis.input
    return {
        "analysis": analysis.model_dump(mode="json"),
        "instrument_rows": [
            r.model_dump(mode="json") for r in occurrence_rows(analysis, PROFILE["stem_model"])
        ],
        "loop_families": loop_family_rows(
            group_loop_families(suggested_intervals(analysis, "master"), analysis.durations["new"])
        ),
        "suggestions": {
            r: {
                "instruments": instrument_prefill(analysis, PROFILE["stem_model"])
                if r == "master"
                else {},
                "intervals": [i.model_dump(mode="json") for i in suggested_intervals(analysis, r)],
                "placement": placement_proposal(
                    suggested_intervals(analysis, r), analysis.durations["new"]
                ).__dict__,
            }
            for r in intake.analysis_scope
        },
    }


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "initial":
        print(json.dumps(initial()))
    else:
        body = json.load(sys.stdin)
        analysis = Analysis.model_validate(body["analysis"])
        if mode == "review":
            print(
                apply_review(
                    analysis, ReviewPayload.model_validate(body["payload"])
                ).model_dump_json()
            )
        elif mode == "html":
            print(document_html(analysis))
        else:
            print(document_text(analysis))
