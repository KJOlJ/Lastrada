import importlib.util
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def bootstrap():
    spec = importlib.util.spec_from_file_location(
        "firebase_bootstrap", ROOT / "deploy/bootstrap.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_deployment_defaults_to_plan_and_requires_specific_approval():
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy/bootstrap.py")], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "PLAN ONLY" in result.stdout
    result = subprocess.run(
        [sys.executable, str(ROOT / "deploy/bootstrap.py"), "--apply"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "after approval" in result.stderr


def test_resource_plan_is_bounded_and_uses_existing_project_model():
    module = bootstrap()
    plan = module.plan("lastrada-64bab", "us-central1")
    assert "max 1" in plan["worker"]
    assert "25-minute" in plan["worker"]
    assert "20 globally" in plan["quotas"]
    assert (
        module.DEFAULT_MODEL
        == "https://storage.googleapis.com/lastrada-model-files-sri/sampleid-best.ckpt"
    )


def test_container_starts_api_not_streamlit_and_excludes_private_files():
    docker = (ROOT / "deploy/Dockerfile").read_text()
    assert "uvicorn lastrada.web.server:app" in docker
    assert "streamlit run" not in docker
    ignored = (ROOT / ".dockerignore").read_text()
    assert ignored.startswith("*\n")
    assert "!checkpoints" not in ignored and "!attachments" not in ignored


def test_apply_plan_uses_private_worker_and_never_enables_billing(monkeypatch, tmp_path):
    import json

    module = bootstrap()
    monkeypatch.setattr(module, "ROOT", tmp_path)
    (tmp_path / "web/public").mkdir(parents=True)
    (tmp_path / "firebase.json").write_text((ROOT / "firebase.json").read_text())
    monkeypatch.setattr(module.shutil, "which", lambda _command: "/tool")
    monkeypatch.setattr(module, "exists", lambda *_args: False)
    calls = []

    def run(*command, capture=False):
        calls.append(command)
        if command[:4] == ("gcloud", "config", "get-value", "account"):
            return "owner@example.test"
        if command[:4] == ("gcloud", "billing", "projects", "describe"):
            return json.dumps({"billingEnabled": True})
        if command[:2] == ("git", "branch"):
            return "local/stem-fast"
        if command[:2] == ("git", "rev-parse"):
            return "a" * 40
        if command[:4] == ("gcloud", "run", "services", "describe"):
            return "https://" + command[4] + ".example.test"
        if "apps:list" in command:
            return json.dumps({"result": [{"platform": "WEB", "appId": "test-app"}]})
        if "hosting:sites:list" in command:
            return json.dumps(
                {"result": {"sites": [{"name": "projects/lastrada-64bab/sites/lastrada-review"}]}}
            )
        if "apps:sdkconfig" in command:
            return json.dumps(
                {"result": {"sdkConfig": {"projectId": "lastrada-64bab", "apiKey": "public-test"}}}
            )
        if "deploy" in command and "hosting" in command:
            hosting = json.loads(Path(command[command.index("--config") + 1]).read_text())
            assert hosting["hosting"]["site"] == "lastrada-review"
        if command[:3] == ("gcloud", "builds", "submit"):
            build = json.loads(Path(command[command.index("--config") + 1]).read_text())
            assert build["steps"][0]["env"] == ["DOCKER_BUILDKIT=1"]
        return "" if capture else None

    monkeypatch.setattr(module, "run", run)
    module.apply(
        "lastrada-64bab",
        "us-central1",
        module.DEFAULT_MODEL,
        app_id="test-app",
        hosting_site="lastrada-review",
        confirm_hosting="lastrada-64bab/lastrada-review",
    )
    deploys = [c for c in calls if c[:3] == ("gcloud", "run", "deploy")]
    worker = next(c for c in deploys if c[3] == "lastrada-worker")
    api = next(c for c in deploys if c[3] == "lastrada-api")
    assert "--no-allow-unauthenticated" in worker
    assert "--max-instances=1" in worker
    assert "--allow-unauthenticated" in api
    assert not any("link" in c and "billing" in c for c in calls)
    assert not any("keys" in c for c in calls)
    config = json.loads((tmp_path / "web/public/config.json").read_text())
    assert config["firebase"]["projectId"] == "lastrada-64bab"
    assert config["build"] == {
        "branch": "local/stem-fast",
        "commit": "a" * 40,
        "profile": "stem-fast",
        "dirty": False,
    }


def test_ambiguous_firebase_targets_stop_before_any_commands(monkeypatch):
    import pytest

    module = bootstrap()
    calls = []
    monkeypatch.setattr(module, "run", lambda *args, **kwargs: calls.append(args))
    for app, site, confirmation in [
        (None, None, None),
        ("app", "site", None),
        ("app", "site", "wrong/site"),
    ]:
        with pytest.raises(SystemExit, match="No targets are inferred"):
            module.select_firebase_target("project", app, site, confirmation)
    assert calls == []


def test_existing_repository_and_queue_fail_closed(monkeypatch):
    import json
    import pytest

    module = bootstrap()
    monkeypatch.setattr(module, "exists", lambda *args: True)
    monkeypatch.setattr(module, "run", lambda *args, **kwargs: json.dumps({"labels": {}}))
    with pytest.raises(SystemExit, match="unmarked Artifact"):
        module.check_existing_targets("project", "us-central1", None)
    monkeypatch.setattr(
        module,
        "run",
        lambda *args, **kwargs: json.dumps({"labels": {"lastrada-managed": "firebase-web"}}),
    )
    with pytest.raises(SystemExit, match="queue ownership"):
        module.check_existing_targets("project", "us-central1", None)
    module.check_existing_targets(
        "project", "us-central1", "projects/project/locations/us-central1/queues/lastrada-analysis"
    )


def test_firebase_app_selection_rejects_another_projects_app(monkeypatch):
    import json
    import pytest

    module = bootstrap()
    monkeypatch.setattr(
        module,
        "run",
        lambda *args, **kwargs: json.dumps(
            {"result": [{"platform": "WEB", "appId": "different-app"}]}
        ),
    )
    with pytest.raises(SystemExit, match="does not belong"):
        module.select_firebase_target("project", "requested-app", "site", "project/site")


def test_missing_cloud_run_service_is_absent_but_denials_still_stop(monkeypatch):
    import pytest

    module = bootstrap()
    command = ("gcloud", "run", "services", "describe", "lastrada-api")

    def response(message):
        monkeypatch.setattr(
            module.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", message)
        )

    response("ERROR: (gcloud.run.services.describe) Cannot find service [lastrada-api]")
    assert module.exists(*command) is False
    response("PERMISSION_DENIED: Cannot find service [lastrada-api]")
    with pytest.raises(SystemExit):
        module.exists(*command)
    response("SERVICE_DISABLED: Cloud Run API is disabled")
    with pytest.raises(SystemExit):
        module.exists(*command)
    response("Cannot find service [another-service]")
    with pytest.raises(SystemExit):
        module.exists(*command)


def test_wrong_branch_or_dirty_source_stops_before_cloud_access(monkeypatch):
    import pytest

    module = bootstrap()
    calls = []

    def fake_run(*command, **kwargs):
        calls.append(command)
        assert command[0] == "git"
        return {"branch": "feat/firebase-web", "rev-parse": "a" * 40, "status": ""}[command[1]]

    monkeypatch.setattr(module, "run", fake_run)
    with pytest.raises(SystemExit, match="Expected branch local/stem-fast"):
        module.apply("lastrada-64bab", "us-central1", module.DEFAULT_MODEL)
    monkeypatch.setattr(
        module,
        "run",
        lambda *args, **kwargs: {
            "branch": "local/stem-fast",
            "rev-parse": "a" * 40,
            "status": " M app.py",
        }[args[1]],
    )
    with pytest.raises(SystemExit, match="preserve local changes"):
        module.apply("lastrada-64bab", "us-central1", module.DEFAULT_MODEL)
