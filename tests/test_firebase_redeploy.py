"""Update-only deployment safety without Google credentials or cloud mutations."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("redeploy", ROOT / "deploy/redeploy.py")
redeploy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(redeploy)
SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64


def service(role):
    cpu, memory, concurrency, maximum, timeout = (
        ("1", "1Gi", 20, "2", 300) if role == "api" else ("2", "4Gi", 1, "1", 1800)
    )
    name = "lastrada-" + role
    return {
        "metadata": {"name": name, "labels": {"lastrada-managed": "firebase-web"}},
        "spec": {
            "template": {
                "metadata": {"annotations": {"autoscaling.knative.dev/maxScale": maximum}},
                "spec": {
                    "serviceAccountName": f"{name}@{redeploy.PROJECT}.iam.gserviceaccount.com",
                    "containerConcurrency": concurrency,
                    "timeoutSeconds": timeout,
                    "containers": [
                        {
                            "image": "registry/old@sha256:old",
                            "resources": {"limits": {"cpu": cpu, "memory": memory}},
                            "env": [
                                {"name": "LASTRADA_SERVICE_MODE", "value": role},
                                {"name": "LASTRADA_ACCESS", "value": "google"},
                                {"name": "LASTRADA_USER_DAILY_JOBS", "value": "25"},
                                {"name": "LASTRADA_DAILY_JOBS", "value": "200"},
                                {
                                    "name": "CUSTOM_SECRET",
                                    "valueFrom": {
                                        "secretKeyRef": {"name": "existing", "key": "latest"}
                                    },
                                },
                            ],
                        }
                    ],
                },
            }
        },
        "status": {
            "url": f"https://{name}.example.test",
            "latestReadyRevisionName": name + "-00001",
            "traffic": [{"revisionName": name + "-00001", "percent": 100}],
        },
    }


@pytest.mark.parametrize("role", ["api", "worker"])
def test_existing_services_have_bounded_resources(role):
    assert redeploy.validate_service(service(role), role).endswith("00001")


@pytest.mark.parametrize("change", ["ownership", "identity", "memory", "maximum", "traffic"])
def test_unexpected_existing_resources_stop_deployment(change):
    state = service("worker")
    spec = state["spec"]["template"]["spec"]
    if change == "ownership":
        state["metadata"]["labels"] = {}
    elif change == "identity":
        spec["serviceAccountName"] = "another@example.test"
    elif change == "memory":
        spec["containers"][0]["resources"]["limits"]["memory"] = "8Gi"
    elif change == "maximum":
        state["spec"]["template"]["metadata"]["annotations"] = {}
    else:
        state["status"]["traffic"] = [{"percent": 50}, {"percent": 50}]
    with pytest.raises(ValueError):
        redeploy.validate_service(state, "worker")


def test_worker_cannot_be_public_and_wrong_site_config_is_rejected():
    with pytest.raises(ValueError, match="private"):
        redeploy.validate_iam({"bindings": [{"members": ["allUsers"]}]}, private=True)
    with pytest.raises(ValueError, match="Firebase app"):
        redeploy.validate_config(
            {"firebase": {"projectId": "different"}}, "https://api.example.test"
        )


def test_version_updates_preserve_unknown_environment_and_secret_references(monkeypatch):
    before = service("api")
    after = deepcopy(before)
    image = "registry/app@" + DIGEST
    container = after["spec"]["template"]["spec"]["containers"][0]
    container["image"] = image
    container["env"].extend(
        [
            {"name": "LASTRADA_BUILD_SHA", "value": SHA},
            {"name": "LASTRADA_BUILD_BRANCH", "value": redeploy.BRANCH},
        ]
    )
    calls = []
    monkeypatch.setattr(redeploy, "run", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        redeploy, "cloud", lambda *args: after if "describe" in args else {"bindings": []}
    )
    state = {"services": {"api": before}, "policies": {"api": {"bindings": []}}}
    redeploy.update_service("api", image, SHA, state)
    assert redeploy.preserved_settings(before) == redeploy.preserved_settings(after)
    assert len(calls) == 2
    assert calls[0][:4] == ("gcloud", "run", "services", "update")
    assert "--update-env-vars" in calls[0] and "--set-env-vars" not in calls[0]
    assert not any("--service-account" in c or "--memory" in c for c in calls)
    container["env"][2]["value"] = "3"
    with pytest.raises(RuntimeError, match="Settings changed"):
        redeploy.update_service("api", image, SHA, state)


def test_missing_permission_is_reported_without_mutating_iam_or_printing_token(monkeypatch):
    calls = []

    def run(*args):
        calls.append(args)
        return "private-token" if "print-access-token" in args else "deployer@example.test"

    monkeypatch.setattr(redeploy, "run", run)
    monkeypatch.setattr(redeploy, "fetch", lambda *args, **kwargs: (200, {}, b'{"permissions":[]}'))
    with pytest.raises(RuntimeError, match="cloudbuild.builds.create") as error:
        redeploy.check_deployment_permissions()
    assert "private-token" not in str(error.value)
    assert len(calls) == 2


def test_build_uses_existing_account_and_returns_immutable_image(monkeypatch, tmp_path):
    calls = []

    def run(*args, **kwargs):
        calls.append(args)
        config = json.loads(Path(args[args.index("--config") + 1]).read_text())
        assert config["serviceAccount"].endswith(
            "lastrada-build@lastrada-64bab.iam.gserviceaccount.com"
        )
        assert "source-" + SHA in config["tags"]
        return json.dumps(
            {
                "id": "generated-build",
                "status": "SUCCESS",
                "results": {"images": [{"name": config["images"][0], "digest": DIGEST}]},
            }
        )

    monkeypatch.setattr(redeploy, "run", run)
    image = redeploy.build_image(tmp_path, SHA, tmp_path)
    assert image.endswith("@" + DIGEST)
    assert len(calls) == 1 and "submit" in calls[0]


def test_backend_verification_failure_rolls_back_before_hosting(monkeypatch, tmp_path):
    state = {
        "services": {role: service(role) for role in ["api", "worker"]},
        "revisions": {role: "lastrada-" + role + "-old" for role in ["api", "worker"]},
    }
    monkeypatch.setattr(redeploy, "build_image", lambda *args: "registry/app@" + DIGEST)
    monkeypatch.setattr(redeploy, "update_service", lambda *args: "new")

    def failed(*args):
        raise RuntimeError("Wrong health version")

    monkeypatch.setattr(redeploy, "verify_api", failed)
    calls = []
    monkeypatch.setattr(redeploy, "run", lambda *args, **kwargs: calls.append(args))
    with pytest.raises(RuntimeError, match="Wrong health"):
        redeploy.deploy(tmp_path, SHA, state, tmp_path)
    assert len(calls) == 2
    assert all("update-traffic" in c and "--to-revisions" in c for c in calls)
    assert calls[0][calls[0].index("--to-revisions") + 1] == "lastrada-api-old=100"


def test_full_update_preserves_firebase_identity_and_checks_live_assets(monkeypatch, tmp_path):
    source = tmp_path / "source"
    (source / "web/public").mkdir(parents=True)
    for name in ["app.js", "auto-instruments.js", "relationship-evidence.js", "index.html"]:
        (source / "web/public" / name).write_text("generated")
    (source / "firebase.json").write_text(json.dumps({"hosting": {"site": redeploy.SITE}}))
    config = {
        "firebase": {
            "projectId": redeploy.PROJECT,
            "appId": redeploy.APP_ID,
            "apiKey": "public-config",
        },
        "apiBase": "https://lastrada-api.example.test",
        "existing": True,
    }
    state = {"services": {role: service(role) for role in ["api", "worker"]}, "config": config}
    monkeypatch.setattr(redeploy, "build_image", lambda *args: "registry/app@" + DIGEST)
    monkeypatch.setattr(redeploy, "update_service", lambda *args: "new")
    monkeypatch.setattr(redeploy, "verify_api", lambda *args: {"status": "ok"})
    calls = []
    monkeypatch.setattr(redeploy, "run", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(
        redeploy,
        "public_json",
        lambda url: json.loads((source / "web/public/config.json").read_text()),
    )
    monkeypatch.setattr(redeploy, "fetch", lambda *args, **kwargs: (200, {}, b"generated"))
    result = redeploy.deploy(source, SHA, state, tmp_path)
    saved = json.loads((source / "web/public/config.json").read_text())
    assert saved["firebase"] == config["firebase"] and saved["existing"] is True
    assert saved["build"]["commit"] == SHA and result["settings_and_iam_preserved"]
    assert len(calls) == 1 and "deploy" in calls[0] and "hosting" in calls[0]
