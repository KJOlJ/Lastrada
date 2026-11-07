"""Production FastAPI app with the consolidated Nature of Use summary."""

from fastapi.routing import APIRoute

from lastrada.reporting.nature_summary import nature_of_use_summary
from lastrada.schemas.models import Analysis
from lastrada.web.server import create_app


app = create_app()


for route in app.routes:
    if not isinstance(route, APIRoute):
        continue
    if route.path != "/api/analyses/{analysis_id}/result":
        continue

    original_result = route.dependant.call

    def result_with_nature_summary(analysis_id, request, _original=original_result):
        payload = _original(analysis_id, request)
        analysis = Analysis.model_validate(payload["analysis"])
        payload["nature_of_use_summary"] = nature_of_use_summary(analysis)
        return payload

    route.endpoint = result_with_nature_summary
    route.dependant.call = result_with_nature_summary
    break
