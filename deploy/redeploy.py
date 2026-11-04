#!/usr/bin/env python3
"""Update the existing Firebase stack without provisioning or changing access."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT = "lastrada-64bab"
REGION = "us-central1"
SITE = "lastrada-alt"
APP_ID = "1:471058014767:web:9b99b922f532c81db5dcda"
BRANCH = "local/stem-fast"
ROOT = Path(__file__).resolve().parents[1]
FIREBASE = ["npx", "--yes", "firebase-tools@15.4.0"]
IDENTITY_ENV = {"LASTRADA_BUILD_SHA", "LASTRADA_BUILD_BRANCH"}


def run(*args, cwd=ROOT):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"{args[0]} {args[1]} failed: {result.stderr[-2500:]}")
    return result.stdout.strip()


def cloud(*args):
    return json.loads(run("gcloud", *args, "--project", PROJECT, "--format=json"))


def fetch(url, *, headers=None, method="GET", data=None):
    request = Request(url, headers=headers or {}, method=method, data=data)
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, dict(response.headers), response.read()
    except HTTPError as error:
        return error.code, dict(error.headers), error.read()


def public_json(url):
    status, _, body = fetch(url)
    if status != 200:
        raise RuntimeError(f"Public verification returned HTTP {status}: {url}")
    return json.loads(body)


def environments(service):
    return {
        x["name"]: x for x in service["spec"]["template"]["spec"]["containers"][0].get("env", [])
    }


def env_value(service, name):
    return environments(service).get(name, {}).get("value")


def preserved_settings(service):
    template = service["spec"]["template"]
    spec = template["spec"]
    annotations = template.get("metadata", {}).get("annotations", {})
    service_annotations = service.get("metadata", {}).get("annotations", {})
    return {
        "identity": spec["serviceAccountName"],
        "resources": spec["containers"][0]["resources"],
        "concurrency": spec["containerConcurrency"],
        "timeout": spec["timeoutSeconds"],
        "environment": {k: v for k, v in environments(service).items() if k not in IDENTITY_ENV},
        "scaling": {
            k: v
            for k, v in annotations.items()
            if k.startswith("autoscaling.")
            or k
            in {
                "run.googleapis.com/cpu-throttling",
                "run.googleapis.com/startup-cpu-boost",
                "run.googleapis.com/execution-environment",
            }
        },
        "service_settings": {
            k: v
            for k, v in service_annotations.items()
            if k
            in {
                "run.googleapis.com/ingress",
                "run.googleapis.com/minScale",
                "run.googleapis.com/maxScale",
                "run.googleapis.com/invoker-iam-disabled",
            }
        },
    }


def validate_service(service, role):
    name = "lastrada-" + role
    if service.get("metadata", {}).get("name") != name:
        raise ValueError("Wrong Cloud Run target")
    if service["metadata"].get("labels", {}).get("lastrada-managed") != "firebase-web":
        raise ValueError(f"Refusing to update an unmarked service: {name}")
    spec = service["spec"]["template"]["spec"]
    if len(spec["containers"]) != 1:
        raise ValueError("Unexpected multi-container service")
    if spec["serviceAccountName"] != f"{name}@{PROJECT}.iam.gserviceaccount.com":
        raise ValueError(f"Unexpected service identity: {name}")
    expected = {"api": (1, "1Gi", 20, 2, 300), "worker": (2, "4Gi", 1, 1, 1800)}[role]
    limits = spec["containers"][0]["resources"]["limits"]
    cpu_text = str(limits["cpu"])
    cpu = float(cpu_text.rstrip("m")) / (1000 if cpu_text.endswith("m") else 1)
    if (cpu, limits["memory"], spec["containerConcurrency"], spec["timeoutSeconds"]) != (
        expected[0],
        expected[1],
        expected[2],
        expected[4],
    ):
        raise ValueError(f"Unexpected resource limits on {name}; inspect before updating")
    annotations = service["spec"]["template"].get("metadata", {}).get("annotations", {})
    top = service["metadata"].get("annotations", {})
    maximum = annotations.get(
        "autoscaling.knative.dev/maxScale", top.get("run.googleapis.com/maxScale")
    )
    if maximum is None or int(maximum) > expected[3] or int(maximum) < 1:
        raise ValueError(f"Missing or excessive instance cap on {name}")
    if int(annotations.get("autoscaling.knative.dev/minScale", "0")) or int(
        top.get("run.googleapis.com/minScale", "0")
    ):
        raise ValueError(f"Unexpected minimum instances on {name}")
    if env_value(service, "LASTRADA_SERVICE_MODE") != role:
        raise ValueError("Unexpected service mode")
    if env_value(service, "LASTRADA_ACCESS") != "google":
        raise ValueError("Verified Google sign-in must remain enabled")
    traffic = service["status"].get("traffic", [])
    active = [x for x in traffic if x.get("percent", 0)]
    if len(active) != 1 or active[0]["percent"] != 100 or any(x.get("tag") for x in traffic):
        raise ValueError("Traffic splits or tagged revisions require explicit review")
    revision = active[0].get("revisionName")
    if not revision or revision != service["status"].get("latestReadyRevisionName"):
        raise ValueError("Existing traffic is not on the latest ready revision")
    return revision


def iam_bindings(policy):
    return sorted(
        json.dumps({**binding, "members": sorted(binding.get("members", []))}, sort_keys=True)
        for binding in policy.get("bindings", [])
    )


def validate_iam(policy, private=False):
    if private and any(
        member in {"allUsers", "allAuthenticatedUsers"}
        for binding in policy.get("bindings", [])
        for member in binding.get("members", [])
    ):
        raise ValueError("Worker must remain private")


def validate_config(config, api_url):
    if (
        config.get("firebase", {}).get("projectId") != PROJECT
        or config["firebase"].get("appId") != APP_ID
    ):
        raise ValueError("Live Firebase app does not match the selected project/app")
    if config.get("apiBase", "").rstrip("/") != api_url.rstrip("/"):
        raise ValueError("Live Firebase site points to a different API")


def check_deployment_permissions():
    # The existing credential stays inside the deployment runner. Only permission
    # names and principal/resource identities are reported; no IAM is changed.
    token = run("gcloud", "auth", "print-access-token")
    caller = run("gcloud", "config", "get-value", "account")
    targets = [
        (
            f"https://cloudresourcemanager.googleapis.com/v1/projects/{PROJECT}:testIamPermissions",
            "cloudbuild.builds.create",
            PROJECT,
        )
    ]
    targets.extend(
        (
            f"https://iam.googleapis.com/v1/projects/-/serviceAccounts/lastrada-{role}@{PROJECT}.iam.gserviceaccount.com:testIamPermissions",
            "iam.serviceAccounts.actAs",
            f"lastrada-{role}@{PROJECT}.iam.gserviceaccount.com",
        )
        for role in ("build", "worker", "api")
    )
    missing = []
    for url, permission, resource in targets:
        status, _, body = fetch(
            url,
            method="POST",
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
            },
            data=json.dumps({"permissions": [permission]}).encode(),
        )
        if status != 200:
            missing.append(f"could not verify {permission} on {resource} (HTTP {status})")
        elif permission not in json.loads(body).get("permissions", []):
            missing.append(f"lacks {permission} on {resource}")
    if missing:
        raise RuntimeError(
            f"Deployment account {caller}: {'; '.join(missing)}. No IAM changes made."
        )


def inspect():
    services, policies, revisions = {}, {}, {}
    for role in ("api", "worker"):
        name = "lastrada-" + role
        services[role] = cloud("run", "services", "describe", name, "--region", REGION)
        revisions[role] = validate_service(services[role], role)
        policies[role] = cloud("run", "services", "get-iam-policy", name, "--region", REGION)
        validate_iam(policies[role], private=role == "worker")
    if env_value(services["api"], "LASTRADA_WORKER_URL") != services["worker"]["status"]["url"]:
        raise ValueError("API points to a different worker")
    origins = env_value(services["api"], "LASTRADA_ORIGINS") or ""
    if f"https://{SITE}.web.app" not in origins.split(","):
        raise ValueError("Existing API does not authorize the selected Hosting origin")
    if (
        env_value(services["api"], "LASTRADA_USER_DAILY_JOBS"),
        env_value(services["api"], "LASTRADA_DAILY_JOBS"),
    ) != ("25", "200"):
        raise ValueError("Existing quotas differ from the current 25/200 testing limits")
    repository = cloud("artifacts", "repositories", "describe", "lastrada", "--location", REGION)
    bucket = cloud("storage", "buckets", "describe", f"gs://{PROJECT}-lastrada-builds")
    for resource in (repository, bucket):
        if resource.get("labels", {}).get("lastrada-managed") != "firebase-web":
            raise ValueError("Build repository/bucket is unmarked; refusing reuse")
    account = cloud(
        "iam", "service-accounts", "describe", f"lastrada-build@{PROJECT}.iam.gserviceaccount.com"
    )
    if account.get("description") != "Managed by Lastrada Firebase web":
        raise ValueError("Existing build account ownership is ambiguous")
    check_deployment_permissions()
    sites = json.loads(run(*FIREBASE, "hosting:sites:list", "--project", PROJECT, "--json"))[
        "result"
    ]
    if isinstance(sites, dict):
        sites = sites.get("sites", [])
    if not any(
        x.get("name") in {f"projects/{PROJECT}/sites/{SITE}", f"projects/471058014767/sites/{SITE}"}
        for x in sites
    ):
        raise ValueError("Selected Hosting site does not exist in this project")
    config = public_json(f"https://{SITE}.web.app/config.json")
    validate_config(config, services["api"]["status"]["url"])
    return {"services": services, "policies": policies, "revisions": revisions, "config": config}


def build_image(source, sha, folder):
    image = f"{REGION}-docker.pkg.dev/{PROJECT}/lastrada/app:{sha[:12]}"
    config = {
        "steps": [
            {
                "name": "gcr.io/cloud-builders/docker",
                "env": ["DOCKER_BUILDKIT=1"],
                "args": [
                    "build",
                    "-f",
                    "deploy/Dockerfile",
                    "--label",
                    f"org.opencontainers.image.revision={sha}",
                    "-t",
                    image,
                    ".",
                ],
            }
        ],
        "images": [image],
        "timeout": "1800s",
        "tags": ["lastrada-update", "source-" + sha],
        "serviceAccount": f"projects/{PROJECT}/serviceAccounts/lastrada-build@{PROJECT}.iam.gserviceaccount.com",
        "options": {"logging": "CLOUD_LOGGING_ONLY"},
    }
    path = folder / "build.json"
    path.write_text(json.dumps(config))
    result = json.loads(
        run(
            "gcloud",
            "builds",
            "submit",
            str(source),
            "--project",
            PROJECT,
            "--config",
            str(path),
            "--gcs-source-staging-dir",
            f"gs://{PROJECT}-lastrada-builds/source",
            "--format=json",
            "--quiet",
            cwd=source,
        )
    )
    if isinstance(result, list) and len(result) == 1:
        result = result[0]
    if result.get("status") != "SUCCESS":
        raise RuntimeError("Cloud Build did not succeed")
    digest = next(x["digest"] for x in result["results"]["images"] if x["name"] == image)
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", digest):
        raise ValueError("Cloud Build returned an invalid image digest")
    print(json.dumps({"build_id": result["id"], "image_digest": digest}), flush=True)
    return image.split(":")[0] + "@" + digest


def update_service(role, image, sha, before):
    name = "lastrada-" + role
    run(
        "gcloud",
        "run",
        "services",
        "update",
        name,
        "--project",
        PROJECT,
        "--region",
        REGION,
        "--image",
        image,
        "--update-env-vars",
        f"LASTRADA_BUILD_SHA={sha},LASTRADA_BUILD_BRANCH={BRANCH}",
        "--quiet",
    )
    run(
        "gcloud",
        "run",
        "services",
        "update-traffic",
        name,
        "--project",
        PROJECT,
        "--region",
        REGION,
        "--to-latest",
        "--quiet",
    )
    after = cloud("run", "services", "describe", name, "--region", REGION)
    validate_service(after, role)
    if preserved_settings(before["services"][role]) != preserved_settings(after):
        raise RuntimeError(f"Settings changed unexpectedly on {name}")
    policy = cloud("run", "services", "get-iam-policy", name, "--region", REGION)
    if iam_bindings(policy) != iam_bindings(before["policies"][role]):
        raise RuntimeError(f"IAM changed unexpectedly on {name}")
    if (
        env_value(after, "LASTRADA_BUILD_SHA") != sha
        or after["spec"]["template"]["spec"]["containers"][0]["image"] != image
    ):
        raise RuntimeError(f"Wrong application version on {name}")
    return after["status"]["latestReadyRevisionName"]


def verify_api(api_url, worker_url, sha):
    health = public_json(api_url + "/health")
    if any(
        health.get(k) != v
        for k, v in {
            "status": "ok",
            "branch": BRANCH,
            "commit": sha,
            "profile": "stem-fast",
        }.items()
    ):
        raise RuntimeError("API health does not match the intended release")
    status, _, _ = fetch(api_url + "/api/analyses/00000000-0000-4000-8000-000000000001")
    if status != 401:
        raise RuntimeError(f"Unsigned API request returned {status}, expected 401")
    status, _, _ = fetch(worker_url + "/health")
    if status not in {401, 403}:
        raise RuntimeError("Worker is not restricted by IAM")
    status, headers, _ = fetch(
        api_url + "/api/analyses",
        method="OPTIONS",
        headers={
            "Origin": f"https://{SITE}.web.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    headers = {k.lower(): v for k, v in headers.items()}
    if status != 200 or headers.get("access-control-allow-origin") != f"https://{SITE}.web.app":
        raise RuntimeError("API CORS check failed")
    return health


def deploy(source, sha, state, folder):
    image = build_image(source, sha, folder)
    changed, revisions = [], {}
    hosting_started = False
    try:
        for role in ("worker", "api"):
            changed.append(role)
            revisions[role] = update_service(role, image, sha, state)
        api_url = state["services"]["api"]["status"]["url"]
        health = verify_api(api_url, state["services"]["worker"]["status"]["url"], sha)
        config = dict(state["config"])
        config["build"] = {"branch": BRANCH, "commit": sha, "profile": "stem-fast", "dirty": False}
        (source / "web/public/config.json").write_text(json.dumps(config, indent=2))
        hosting = json.loads((source / "firebase.json").read_text())
        if hosting.get("hosting", {}).get("site") != SITE:
            raise ValueError("Source targets a different Hosting site")
        hosting_started = True
        run(
            *FIREBASE,
            "deploy",
            "--only",
            "hosting",
            "--project",
            PROJECT,
            "--config",
            "firebase.json",
            "--non-interactive",
            cwd=source,
        )
        for attempt in range(6):
            live = public_json(f"https://{SITE}.web.app/config.json?release={sha}")
            if live.get("build") == config["build"]:
                break
            if attempt == 5:
                raise RuntimeError("Hosting did not serve the intended version")
            time.sleep(5)
        validate_config(live, api_url)
        for asset in ("app.js", "auto-instruments.js", "relationship-evidence.js", "index.html"):
            status, _, body = fetch(f"https://{SITE}.web.app/{asset}?release={sha}")
            if (
                status != 200
                or hashlib.sha256(body).digest()
                != hashlib.sha256((source / "web/public" / asset).read_bytes()).digest()
            ):
                raise RuntimeError("Hosting asset mismatch: " + asset)
        result = {
            "site": f"https://{SITE}.web.app",
            "commit": sha,
            "image": image,
            "revisions": revisions,
            "health": health,
            "settings_and_iam_preserved": True,
        }
        print(json.dumps(result, indent=2), flush=True)
        print("::notice title=LaStrada deployed::" + json.dumps(result), flush=True)
        return result
    except Exception:
        if not hosting_started:
            for role in reversed(changed):
                run(
                    "gcloud",
                    "run",
                    "services",
                    "update-traffic",
                    "lastrada-" + role,
                    "--project",
                    PROJECT,
                    "--region",
                    REGION,
                    "--to-revisions",
                    state["revisions"][role] + "=100",
                    "--quiet",
                )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("inspect", "apply"), default="inspect")
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-f0-9]{40}", args.sha):
        raise SystemExit("A full source commit SHA is required")
    run("git", "merge-base", "--is-ancestor", args.sha, "origin/" + BRANCH)
    profile = json.loads(run("git", "show", args.sha + ":configs/web-profile.json"))
    if profile.get("source_branch") != BRANCH or profile.get("name") != "stem-fast":
        raise SystemExit("Wrong analysis source/profile")
    state = inspect()
    print(
        json.dumps(
            {
                "project": PROJECT,
                "site": SITE,
                "app": APP_ID,
                "source_sha": args.sha,
                "current_revisions": state["revisions"],
                "origins": env_value(state["services"]["api"], "LASTRADA_ORIGINS"),
                "daily_limits": [25, 200],
                "operation": args.mode,
            },
            indent=2,
        ),
        flush=True,
    )
    print(
        "::notice title=LaStrada inspected::"
        + json.dumps(
            {
                "project": PROJECT,
                "site": SITE,
                "app": APP_ID,
                "source_sha": args.sha,
                "current_revisions": state["revisions"],
                "current_images": {
                    k: v["spec"]["template"]["spec"]["containers"][0]["image"]
                    for k, v in state["services"].items()
                },
                "api_url": state["services"]["api"]["status"]["url"],
                "origins": env_value(state["services"]["api"], "LASTRADA_ORIGINS"),
                "daily_limits": [25, 200],
                "mode": args.mode,
            }
        ),
        flush=True,
    )
    if args.mode == "inspect":
        return
    with tempfile.TemporaryDirectory() as directory:
        folder = Path(directory)
        source = folder / "source"
        source.mkdir()
        archive = folder / "source.tar"
        run("git", "archive", "--format=tar", "--output", str(archive), args.sha)
        with tarfile.open(archive) as stream:
            stream.extractall(source, filter="data")
        deploy(source, args.sha, state, folder)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = str(error).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print("::error title=LaStrada deployment stopped::" + message, flush=True)
        raise
