from copy import deepcopy
from uuid import UUID
from unittest.mock import Mock
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("google.cloud.tasks_v2")
from fastapi.testclient import TestClient
from fastapi import HTTPException
from google.api_core.exceptions import NotFound, PreconditionFailed
from lastrada.web.server import create_app
from lastrada.web.cloud import prefix
from lastrada.web.domain import owner_key


class MemoryCases:
    def __init__(self):
        self.data = {}
        self.requests = 0

    def read(self, path):
        if path not in self.data:
            raise NotFound("not found")
        data, generation = self.data[path]
        return deepcopy(data), generation

    def write(self, path, data, generation=None):
        old = self.data.get(path, ({}, 0))[1]
        if generation is not None and old != generation:
            raise PreconditionFailed("changed")
        self.data[path] = deepcopy(data), old + 1

    def quota(self, owner):
        self.requests += 1

    def upload_session(self, path, upload, origin):
        return "https://upload.example/" + path

    def validate_upload(self, path, expected_size):
        assert expected_size == 10


def payload():
    return {
        "original": {"name": "source.mp3", "size": 10},
        "new": {"name": "new.mp3", "size": 10},
        "credits": {
            "original_title": "Source",
            "original_artist": "Test",
            "new_title": "Mix",
            "new_artist": "Test",
        },
    }


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setenv("LASTRADA_ORIGINS", "https://lastrada-64bab.web.app")
    cases, queue = MemoryCases(), Mock()

    def auth(request):
        token = request.headers.get("authorization")
        if token not in ("Bearer alice", "Bearer bob"):
            raise HTTPException(401)
        return owner_key(token)

    app = create_app(cases, queue, auth, mode="api")
    return TestClient(app), cases, queue


def test_upload_ownership_auth_and_idempotent_queue(service):
    client, cases, queue = service
    assert client.post("/api/analyses", json=payload()).status_code == 401
    headers = {"Authorization": "Bearer alice", "Origin": "https://lastrada-64bab.web.app"}
    response = client.post("/api/analyses", json=payload(), headers=headers)
    assert response.status_code == 200
    analysis_id = response.json()["id"]
    assert UUID(analysis_id)
    assert (
        client.get(
            f"/api/analyses/{analysis_id}", headers={"Authorization": "Bearer bob"}
        ).status_code
        == 404
    )
    assert client.post(f"/api/analyses/{analysis_id}/run", headers=headers).status_code == 200
    assert client.post(f"/api/analyses/{analysis_id}/run", headers=headers).status_code == 200
    assert queue.enqueue.call_count == 1
    assert cases.requests == 1


def test_untrusted_origin_and_worker_route_are_not_public(service):
    client, _, _ = service
    headers = {"Authorization": "Bearer alice", "Origin": "https://untrusted.example"}
    assert client.post("/api/analyses", json=payload(), headers=headers).status_code == 403
    assert client.post("/internal/process", json={}).status_code == 404


def test_incomplete_result_cannot_export_nature_of_use(service):
    from lastrada.schemas.models import Analysis, Intake, Work

    client, cases, _ = service
    headers = {"Authorization": "Bearer alice", "Origin": "https://lastrada-64bab.web.app"}
    analysis_id = client.post("/api/analyses", json=payload(), headers=headers).json()["id"]
    root = prefix(owner_key("Bearer alice"), analysis_id)
    state, generation = cases.read(root + "/case.json")
    state["status"] = "completed"
    cases.write(root + "/case.json", state, generation)
    intake = Intake(
        case_id=analysis_id,
        original_work=Work(title="Source", artist="Test"),
        new_work=Work(title="Mix", artist="Test"),
        analysis_scope=["master", "publishing"],
    )
    cases.write(
        root + "/result.json", Analysis(case_id=analysis_id, input=intake).model_dump(mode="json")
    )
    assert (
        client.get(f"/api/analyses/{analysis_id}/export/html", headers=headers).status_code == 409
    )
    assert (
        client.get(f"/api/analyses/{analysis_id}/export/json", headers=headers).status_code == 200
    )


def test_verified_google_identity_is_required(monkeypatch):
    import firebase_admin
    from firebase_admin import auth
    from starlette.requests import Request
    from lastrada.web.server import authenticate

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "lastrada-64bab")
    monkeypatch.setenv("LASTRADA_ACCESS", "google")
    monkeypatch.setattr(firebase_admin, "initialize_app", lambda **_kwargs: None)
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer test")]})
    claims = {
        "uid": "alice",
        "email": "alice@example.test",
        "email_verified": True,
        "firebase": {"sign_in_provider": "google.com"},
    }
    monkeypatch.setattr(auth, "verify_id_token", lambda *_args: claims)
    assert authenticate(request) == owner_key("alice")
    claims["firebase"]["sign_in_provider"] = "anonymous"
    with pytest.raises(HTTPException) as exc:
        authenticate(request)
    assert exc.value.status_code == 403
    claims["firebase"]["sign_in_provider"] = "google.com"
    claims["email_verified"] = False
    with pytest.raises(HTTPException):
        authenticate(request)


def test_daily_quota_rejects_excess_work(monkeypatch):
    from lastrada.web.cloud import Cases

    monkeypatch.setenv("LASTRADA_USER_DAILY_JOBS", "1")
    memory = MemoryCases()
    store = Cases.__new__(Cases)
    store.read = memory.read
    store.write = memory.write
    store.quota(owner_key("alice"))
    with pytest.raises(ValueError, match="limit"):
        store.quota(owner_key("alice"))


def test_cloud_task_targets_private_worker_with_oidc(monkeypatch):
    from lastrada.web.cloud import Queue
    from google.cloud import tasks_v2

    mock = Mock()
    mock.queue_path.return_value = (
        "projects/lastrada-64bab/locations/us-central1/queues/lastrada-analysis"
    )
    monkeypatch.setattr(tasks_v2, "CloudTasksClient", lambda: mock)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "lastrada-64bab")
    monkeypatch.setenv("LASTRADA_WORKER_URL", "https://worker.example")
    monkeypatch.setenv("LASTRADA_TASK_ACCOUNT", "tasks@example.iam.gserviceaccount.com")
    Queue().enqueue(
        owner_key("alice"), "00000000-0000-4000-8000-000000000001", "analyze", "job-test"
    )
    task = mock.create_task.call_args.kwargs["task"]
    assert task["http_request"]["url"] == "https://worker.example/internal/process"
    assert task["http_request"]["oidc_token"]["audience"] == "https://worker.example"
    assert task["dispatch_deadline"].seconds == 1800


def test_per_moment_check_upgrades_legacy_results_and_reuses_complete_rows(service):
    from lastrada.schemas.models import Analysis, Intake, Work, Interval, StemEvidence
    from lastrada.separation.occurrences import occurrence_rows

    client, cases, queue = service
    headers = {"Authorization": "Bearer alice", "Origin": "https://lastrada-64bab.web.app"}
    analysis_id = client.post("/api/analyses", json=payload(), headers=headers).json()["id"]
    root = prefix(owner_key("Bearer alice"), analysis_id)
    state, _ = cases.read(root + "/case.json")
    state["status"] = "completed"
    cases.write(root + "/case.json", state)
    intake = Intake(
        case_id=analysis_id,
        original_work=Work(title="Source", artist="Test"),
        new_work=Work(title="Mix", artist="Test"),
        analysis_scope=["master", "publishing"],
    )
    result = Analysis(case_id=analysis_id, input=intake, durations={"new": 20, "original": 20})
    result.master.locate.sample_occurrences = [
        Interval(new_start=1, new_end=5, original_start=2, original_end=6, source="sampleid")
    ]
    result.stem_evidence = [
        StemEvidence(
            candidate_number=1,
            source_stem="bass",
            new_song_stem="bass",
            dtw_result="accepted",
            interpretation="legacy",
            reason="one short region",
        )
    ]
    cases.write(root + "/result.json", result.model_dump(mode="json"))
    response = client.get(f"/api/analyses/{analysis_id}/result", headers=headers).json()
    assert response["instrument_rows"][0]["status"] == "pending"
    assert response["suggestions"]["master"]["instruments"] == {}
    assert client.post(f"/api/analyses/{analysis_id}/stems", headers=headers).status_code == 200
    assert queue.enqueue.call_count == 1
    # Repeat while in progress reuses the same job and quota.
    client.post(f"/api/analyses/{analysis_id}/stems", headers=headers)
    assert queue.enqueue.call_count == 1
    result.instrument_occurrences = occurrence_rows(result)
    result.instrument_occurrences[0].status = "checked"
    result.instrument_occurrences[0].suggested_instruments = ["Bass"]
    cases.write(root + "/result.json", result.model_dump(mode="json"))
    state["status"] = "completed"
    cases.write(root + "/case.json", state)
    client.post(f"/api/analyses/{analysis_id}/stems", headers=headers)
    assert queue.enqueue.call_count == 1
    assert cases.requests == 2  # One upload reservation, one instrument job.
    response = client.get(f"/api/analyses/{analysis_id}/result", headers=headers).json()
    assert response["suggestions"]["master"]["instruments"]["element"] == "Bass"
    assert response["suggestions"]["publishing"]["instruments"] == {}
