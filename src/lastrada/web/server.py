"""FastAPI service for Firebase Hosting. Heavy models are imported by workers only."""

import os
import time
import subprocess
import sys
import signal
from threading import Lock
from uuid import UUID, uuid4
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from google.api_core.exceptions import NotFound, PreconditionFailed
from lastrada.web.domain import CreateAnalysis, ReviewPayload, owner_key, apply_review
from lastrada.web.cloud import Cases, Queue, prefix

WORKER_LOCK = Lock()


def authenticate(request):
    import firebase_admin
    from firebase_admin import auth

    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Sign in with Google to continue")
    try:
        if not firebase_admin._apps:
            firebase_admin.initialize_app(options={"projectId": os.environ["GOOGLE_CLOUD_PROJECT"]})
        user = auth.verify_id_token(header[7:])
    except Exception:
        raise HTTPException(401, "Your sign-in expired. Please sign in again.") from None
    if (
        not user.get("email_verified")
        or user.get("firebase", {}).get("sign_in_provider") != "google.com"
    ):
        raise HTTPException(403, "A verified Google sign-in is required")
    if os.getenv("LASTRADA_ACCESS", "allowlist") != "google":
        allowed = {
            x.strip().lower()
            for x in os.getenv("LASTRADA_ALLOWED_EMAILS", "").split(",")
            if x.strip()
        }
        if user.get("email", "").lower() not in allowed:
            raise HTTPException(403, "This account does not have workspace access")
    return owner_key(user["uid"])


def create_app(cases=None, queue=None, authenticate_user=None, mode=None):
    app = FastAPI(title="Lastrada", docs_url=None, redoc_url=None)
    origins = [x.strip() for x in os.getenv("LASTRADA_ORIGINS", "").split(",") if x.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST", "PUT"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def repo():
        nonlocal cases
        if cases is None:
            cases = Cases()
        return cases

    def dispatcher():
        nonlocal queue
        if queue is None:
            queue = Queue()
        return queue

    def user(request):
        return (authenticate_user or authenticate)(request)

    def read_case(request, analysis_id):
        root = prefix(user(request), analysis_id)
        try:
            state, generation = repo().read(root + "/case.json")
            return root, state, generation
        except NotFound:
            raise HTTPException(404, "This sample was not found or has expired") from None

    def result_at(root):
        from lastrada.schemas.models import Analysis

        value, _ = repo().read(root + "/result.json")
        return Analysis.model_validate(value)

    @app.exception_handler(ValueError)
    async def invalid(_request, exc):
        from fastapi.responses import JSONResponse

        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.get("/health")
    def health():
        return {"status": "ok", "revision": os.getenv("K_REVISION", "local")}

    if (mode or os.getenv("LASTRADA_SERVICE_MODE", "api")) == "worker":

        @app.post("/internal/process")
        def process(task: dict):
            # Cloud Run IAM restricts this entire service to the task account.
            import re

            if not re.fullmatch(r"[a-f0-9]{64}", str(task.get("owner", ""))):
                raise HTTPException(400, "Invalid case owner")
            UUID(str(task.get("analysis_id")))
            if task.get("operation") not in ("analyze", "stems"):
                raise HTTPException(400, "Invalid operation")
            root = prefix(task["owner"], task["analysis_id"])
            state, _ = repo().read(root + "/case.json")
            if state.get("task_id") != task.get("task_id") or state["status"] in (
                "completed",
                "failed",
            ):
                return {"status": "already handled"}
            if not WORKER_LOCK.acquire(blocking=False):
                raise HTTPException(503, "Worker busy")
            child = None
            try:
                child = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "lastrada.web.execute",
                        task["owner"],
                        task["analysis_id"],
                        task["operation"],
                        task["task_id"],
                    ],
                    start_new_session=True,
                )
                try:
                    returncode = child.wait(timeout=1500)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
                    returncode = -1
                if returncode:
                    state, generation = repo().read(root + "/case.json")
                    if state.get("task_id") == task["task_id"]:
                        state.update(
                            status="completed" if task["operation"] == "stems" else "failed",
                            error="The optional instrument check could not finish. Your main analysis is preserved."
                            if task["operation"] == "stems"
                            else "Analysis could not finish. Try a shorter recording or another sample.",
                        )
                        repo().write(root + "/case.json", state, generation)
                return {"status": "handled"}
            finally:
                WORKER_LOCK.release()

        return app

    @app.post("/api/analyses")
    def reserve(body: CreateAnalysis, request: Request):
        owner = user(request)
        origin = request.headers.get("origin")
        if origin not in origins:
            raise HTTPException(403, "This site is not authorized to upload")
        repo().quota(owner)  # Bound abandoned uploads as well as compute requests.
        analysis_id = str(uuid4())
        root = prefix(owner, analysis_id)
        state = {
            "id": analysis_id,
            "status": "uploading",
            "created": time.time(),
            "credits": body.credits.model_dump(),
            "uploads": {"original": body.original.model_dump(), "new": body.new.model_dump()},
            "operation": "analyze",
            "error": None,
        }
        repo().write(root + "/case.json", state, 0)
        urls = {
            role: repo().upload_session(root + f"/{role}", upload, origin)
            for role, upload in [("original", body.original), ("new", body.new)]
        }
        return {"id": analysis_id, "uploads": urls}

    def enqueue(request, analysis_id, operation):
        root, state, generation = read_case(request, analysis_id)
        if state["status"] in ("queued", "running"):
            return state
        if operation == "stems":
            if state["status"] != "completed":
                raise ValueError("Finish the main analysis first")
            result = result_at(root)
            from lastrada.separation.occurrences import instrument_check_complete, occurrence_rows

            if instrument_check_complete(result):
                return state
            if not any(row.status in {"pending", "failed"} for row in occurrence_rows(result)):
                raise ValueError("A paired region of at least two seconds is needed for instruments")
            repo().quota(user(request))
        else:
            if state["status"] != "uploading":
                return state  # Never restart an expensive completed request on a duplicate click.
            for role in ("original", "new"):
                repo().validate_upload(root + f"/{role}", state["uploads"][role]["size"])
        task_id = f"{analysis_id}-{operation}-{uuid4().hex[:8]}"
        state.update(status="queued", operation=operation, task_id=task_id, error=None)
        try:
            repo().write(root + "/case.json", state, generation)
        except PreconditionFailed:
            raise HTTPException(409, "This request is already being processed") from None
        try:
            dispatcher().enqueue(user(request), analysis_id, operation, task_id)
        except Exception:
            state.update(
                status="completed" if operation == "stems" else "failed",
                error="The queue is unavailable. Try again shortly.",
            )
            repo().write(root + "/case.json", state)
            raise HTTPException(503, "The queue is unavailable. Try again shortly.") from None
        return state

    @app.post("/api/analyses/{analysis_id}/run")
    def run(analysis_id: UUID, request: Request):
        return enqueue(request, analysis_id, "analyze")

    @app.post("/api/analyses/{analysis_id}/stems")
    def stems(analysis_id: UUID, request: Request):
        return enqueue(request, analysis_id, "stems")

    @app.get("/api/analyses/{analysis_id}")
    def status(analysis_id: UUID, request: Request):
        root, state, _ = read_case(request, analysis_id)
        return {
            "id": state["id"],
            "status": state["status"],
            "operation": state["operation"],
            "error": state.get("error"),
            "instrument_progress": state.get("instrument_progress"),
        }

    @app.get("/api/analyses/{analysis_id}/result")
    def result(analysis_id: UUID, request: Request):
        root, state, _ = read_case(request, analysis_id)
        if state["status"] != "completed":
            raise HTTPException(409, "Analysis is not ready")
        value = result_at(root)
        from lastrada.reporting.suggestions import suggested_intervals, placement_proposal
        from lastrada.reporting.document import missing_document_inputs
        from lastrada.separation.occurrences import occurrence_rows, instrument_prefill

        return {
            "analysis": value.model_dump(mode="json"),
            "missing": missing_document_inputs(value),
            "instrument_rows": [row.model_dump(mode="json") for row in occurrence_rows(value)],
            "suggestions": {
                r: {
                    "intervals": [i.model_dump(mode="json") for i in suggested_intervals(value, r)],
                    "instruments": instrument_prefill(value) if r == "master" else {},
                    "placement": placement_proposal(
                        suggested_intervals(value, r), value.durations["new"]
                    ).__dict__,
                }
                for r in value.input.analysis_scope
            },
        }

    @app.put("/api/analyses/{analysis_id}/review")
    def review(analysis_id: UUID, body: ReviewPayload, request: Request):
        root, state, _ = read_case(request, analysis_id)
        if state["status"] != "completed":
            raise HTTPException(409, "Wait for analysis to finish")
        current, generation = repo().read(root + "/result.json")
        from lastrada.schemas.models import Analysis

        reviewed = apply_review(Analysis.model_validate(current), body)
        try:
            repo().write(root + "/result.json", reviewed.model_dump(mode="json"), generation)
        except PreconditionFailed:
            raise HTTPException(
                409, "This sample changed in another window. Reload it first."
            ) from None
        return {"analysis": reviewed.model_dump(mode="json")}

    @app.get("/api/analyses/{analysis_id}/comparison")
    def comparison(analysis_id: UUID, request: Request):
        root, _state, _ = read_case(request, analysis_id)
        data, _ = repo().read(root + "/comparison.json")
        return data

    @app.get("/api/analyses/{analysis_id}/audio/{role}")
    def audio(analysis_id: UUID, role: str, request: Request):
        if role not in ("original", "new"):
            raise HTTPException(404)
        root, state, _ = read_case(request, analysis_id)
        return StreamingResponse(
            repo().stream(root + f"/{role}"), media_type=state["uploads"][role]["content_type"]
        )

    @app.get("/api/analyses/{analysis_id}/export/{kind}")
    def export(analysis_id: UUID, kind: str, request: Request):
        root, state, _ = read_case(request, analysis_id)
        if state["status"] != "completed":
            raise HTTPException(409, "Analysis is not ready")
        analysis = result_at(root)
        from lastrada.reporting.document import (
            document_text,
            document_html,
            missing_document_inputs,
        )

        if kind == "json":
            return Response(analysis.model_dump_json(indent=2), media_type="application/json")
        if missing_document_inputs(analysis) or analysis.review.status != "approved":
            raise HTTPException(409, "Complete and review your Nature of Use before exporting")
        if kind == "html":
            return Response(document_html(analysis), media_type="text/html")
        if kind == "text":
            return Response(document_text(analysis), media_type="text/plain")
        raise HTTPException(404)

    return app


app = create_app()
