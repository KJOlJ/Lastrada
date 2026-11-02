#!/usr/bin/env python3
"""Print a deployment plan; provision only with explicit resource approval.

Run from an authenticated Google Cloud Shell checkout. This script never creates
service-account keys, activates billing, or changes an existing Streamlit app.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PROFILE = json.loads((ROOT / "configs/web-profile.json").read_text())
DEFAULT_MODEL = "https://storage.googleapis.com/lastrada-model-files-sri/sampleid-best.ckpt"


def plan(project, region):
    return {
        "project": project,
        "region": region,
        "hosting": "Firebase Hosting; Google sign-in available to all verified Google users",
        "analysis_profile": PROFILE,
        "api": "1 CPU / 1 GiB; min 0, max 2 instances; concurrency 20; public HTTPS, Firebase authentication required",
        "worker": "2 CPUs / 4 GiB; min 0, max 1 instance; concurrency 1; private IAM access; 25-minute execution cap",
        "queue": "one concurrent dispatch; 3 attempts; 1 dispatch/second",
        "quotas": "3 reservations/instrument requests per user and 20 globally per UTC day",
        "buckets": [
            f"{project}-lastrada-cases (private, 7-day cleanup)",
            f"{project}-lastrada-builds (private, 1-day cleanup)",
        ],
        "service_accounts": ["lastrada-api", "lastrada-worker", "lastrada-tasks", "lastrada-build"],
        "permissions": "bucket-scoped object access; task enqueue and task-account actAs; task-only worker invocation; build-repository writer and logging",
        "billing": "Existing billing must already be enabled. Cloud Run, builds, tasks and storage may incur charges. Limits bound workload, not an exact bill.",
    }


def run(*command, capture=False):
    result = subprocess.run(list(command), cwd=ROOT, check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else None


def source_identity(expected_branch=None, *, require_clean=False):
    branch = run("git", "branch", "--show-current", capture=True)
    commit = run("git", "rev-parse", "HEAD", capture=True)
    dirty = bool(run("git", "status", "--porcelain", capture=True))
    if expected_branch and branch != expected_branch:
        raise SystemExit(
            f"Expected branch {expected_branch}; checked out {branch or 'detached HEAD'}. No cloud commands executed."
        )
    if require_clean and dirty:
        raise SystemExit(
            "Commit or preserve local changes before deployment. The build must match its recorded commit. No cloud commands executed."
        )
    return {"branch": branch, "commit": commit, "profile": PROFILE["name"], "dirty": dirty}


def exists(*command):
    result = subprocess.run(list(command), cwd=ROOT, capture_output=True, text=True)
    if result.returncode == 0:
        return True
    reason = result.stderr.lower()
    missing_run_service = (
        command[:4] == ("gcloud", "run", "services", "describe")
        and len(command) > 4
        and f"cannot find service [{command[4].lower()}]" in reason
        and not any(
            x in reason for x in ("permission_denied", "permission denied", "service_disabled")
        )
    )
    if missing_run_service or any(
        marker in reason for marker in ("not_found", "not found", "does not exist", "404")
    ):
        return False
    raise SystemExit(
        "Could not inspect the target resource. Resolve the CLI/access error before retrying: "
        + result.stderr[-1200:]
    )


def check_managed_bucket(bucket):
    data = json.loads(
        run(
            "gcloud",
            "storage",
            "buckets",
            "describe",
            f"gs://{bucket}",
            "--format=json",
            capture=True,
        )
    )
    if data.get("labels", {}).get("lastrada-managed") != "firebase-web":
        raise SystemExit(
            f"Refusing to change retention/access on existing unmarked bucket {bucket}. Review it manually first."
        )


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2))
    return str(path)


def select_firebase_target(project, app_id, hosting_site, confirm_hosting):
    """Require exact app/site selection before any provisioning or content writes."""
    if not app_id or not hosting_site or confirm_hosting != f"{project}/{hosting_site}":
        raise SystemExit(
            "Select --firebase-app-id and --hosting-site, and explicitly approve replacing "
            "that site's content with --confirm-hosting PROJECT/SITE. No targets are inferred."
        )
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,62}", hosting_site):
        raise SystemExit("Invalid Hosting site ID")
    firebase = ["npx", "--yes", "firebase-tools@15.4.0"]
    run(*firebase, "login", "--no-localhost")
    apps = json.loads(run(*firebase, "apps:list", "--project", project, "--json", capture=True))[
        "result"
    ]
    if isinstance(apps, dict):
        apps = apps.get("apps", [])
    if not any(a.get("platform") == "WEB" and a.get("appId") == app_id for a in apps):
        raise SystemExit("The explicitly selected Firebase WEB app does not belong to this project")
    config = json.loads(
        run(
            *firebase, "apps:sdkconfig", "WEB", app_id, "--project", project, "--json", capture=True
        )
    )["result"]["sdkConfig"]
    if config.get("projectId") != project:
        raise SystemExit("Firebase SDK configuration project does not match the target")
    sites = json.loads(
        run(*firebase, "hosting:sites:list", "--project", project, "--json", capture=True)
    )["result"]
    if isinstance(sites, dict):
        sites = sites.get("sites", [])
    expected = f"projects/{project}/sites/{hosting_site}"
    if not any(x.get("name") == expected for x in sites):
        raise SystemExit(
            "Selected Hosting site was not found in this project; create/select it explicitly"
        )
    return firebase, config


def check_existing_targets(project, region, approved_queue):
    repo_command = (
        "gcloud",
        "artifacts",
        "repositories",
        "describe",
        "lastrada",
        "--location",
        region,
        "--project",
        project,
    )
    if exists(*repo_command):
        data = json.loads(run(*repo_command, "--format=json", capture=True))
        if data.get("labels", {}).get("lastrada-managed") != "firebase-web":
            raise SystemExit(
                "Refusing to reuse existing unmarked Artifact Registry repository lastrada"
            )
    queue_command = (
        "gcloud",
        "tasks",
        "queues",
        "describe",
        "lastrada-analysis",
        "--location",
        region,
        "--project",
        project,
    )
    queue_name = f"projects/{project}/locations/{region}/queues/lastrada-analysis"
    if exists(*queue_command) and approved_queue != queue_name:
        raise SystemExit(
            "Existing queue ownership cannot be established. Review its jobs/settings and explicitly "
            "approve adopting it with --approve-existing-queue " + queue_name
        )


def apply(
    project,
    region,
    model_url,
    *,
    app_id=None,
    hosting_site=None,
    confirm_hosting=None,
    approved_queue=None,
    expected_branch=None,
):
    build_source = source_identity(expected_branch or PROFILE["source_branch"], require_clean=True)
    if not shutil.which("gcloud") or not shutil.which("npx"):
        raise SystemExit("Run this in Google Cloud Shell, which supplies gcloud and Node.js.")
    account = run("gcloud", "config", "get-value", "account", capture=True)
    if not account or account == "(unset)":
        raise SystemExit("Sign in to gcloud with a project administrator before applying.")
    billing = json.loads(
        run("gcloud", "billing", "projects", "describe", project, "--format=json", capture=True)
    )
    if not billing.get("billingEnabled"):
        raise SystemExit(
            "Billing is not enabled. No billing changes were made; obtain approval before enabling it."
        )
    firebase, firebase_config = select_firebase_target(
        project, app_id, hosting_site, confirm_hosting
    )
    check_existing_targets(project, region, approved_queue)
    services = [
        "run.googleapis.com",
        "cloudbuild.googleapis.com",
        "artifactregistry.googleapis.com",
        "cloudtasks.googleapis.com",
        "storage.googleapis.com",
        "iam.googleapis.com",
        "identitytoolkit.googleapis.com",
        "firebase.googleapis.com",
        "firebasehosting.googleapis.com",
    ]
    run("gcloud", "services", "enable", *services, "--project", project)
    names = ["api", "worker", "tasks", "build"]
    emails = {name: f"lastrada-{name}@{project}.iam.gserviceaccount.com" for name in names}
    for name in names:
        if not exists(
            "gcloud", "iam", "service-accounts", "describe", emails[name], "--project", project
        ):
            run(
                "gcloud",
                "iam",
                "service-accounts",
                "create",
                f"lastrada-{name}",
                "--description=Managed by Lastrada Firebase web",
                "--project",
                project,
            )
        else:
            existing = json.loads(
                run(
                    "gcloud",
                    "iam",
                    "service-accounts",
                    "describe",
                    emails[name],
                    "--project",
                    project,
                    "--format=json",
                    capture=True,
                )
            )
            if existing.get("description") != "Managed by Lastrada Firebase web":
                raise SystemExit(
                    "Refusing to attach roles to an existing unmarked service account: "
                    + emails[name]
                )
    artifacts = f"{region}-docker.pkg.dev/{project}/lastrada/app"
    if not exists(
        "gcloud",
        "artifacts",
        "repositories",
        "describe",
        "lastrada",
        "--location",
        region,
        "--project",
        project,
    ):
        run(
            "gcloud",
            "artifacts",
            "repositories",
            "create",
            "lastrada",
            "--repository-format=docker",
            "--labels=lastrada-managed=firebase-web",
            "--location",
            region,
            "--project",
            project,
        )
    run(
        "gcloud",
        "artifacts",
        "repositories",
        "add-iam-policy-binding",
        "lastrada",
        "--location",
        region,
        "--project",
        project,
        "--member",
        f"serviceAccount:{emails['build']}",
        "--role",
        "roles/artifactregistry.writer",
    )
    run(
        "gcloud",
        "projects",
        "add-iam-policy-binding",
        project,
        "--member",
        f"serviceAccount:{emails['build']}",
        "--role",
        "roles/logging.logWriter",
        "--condition=None",
    )
    cases = f"{project}-lastrada-cases"
    builds = f"{project}-lastrada-builds"
    origins = [f"https://{hosting_site}.web.app", f"https://{hosting_site}.firebaseapp.com"]
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        for bucket, days in [(cases, 7), (builds, 1)]:
            bucket_exists = exists("gcloud", "storage", "buckets", "describe", f"gs://{bucket}")
            if bucket_exists:
                check_managed_bucket(bucket)
            else:
                run(
                    "gcloud",
                    "storage",
                    "buckets",
                    "create",
                    f"gs://{bucket}",
                    "--project",
                    project,
                    "--location",
                    region,
                    "--uniform-bucket-level-access",
                )
            if not bucket_exists:
                run(
                    "gcloud",
                    "storage",
                    "buckets",
                    "update",
                    f"gs://{bucket}",
                    "--update-labels=lastrada-managed=firebase-web",
                )
            run(
                "gcloud",
                "storage",
                "buckets",
                "update",
                f"gs://{bucket}",
                "--public-access-prevention",
                "--lifecycle-file",
                write_json(
                    temp / "lifecycle.json",
                    {"rule": [{"action": {"type": "Delete"}, "condition": {"age": days}}]},
                ),
            )
        run(
            "gcloud",
            "storage",
            "buckets",
            "update",
            f"gs://{cases}",
            "--cors-file",
            write_json(
                temp / "cors.json",
                [
                    {
                        "origin": origins,
                        "method": ["PUT", "POST", "GET", "HEAD"],
                        "responseHeader": ["Content-Type", "Location", "Range", "ETag"],
                        "maxAgeSeconds": 3600,
                    }
                ],
            ),
        )
        for name in ("api", "worker"):
            run(
                "gcloud",
                "storage",
                "buckets",
                "add-iam-policy-binding",
                f"gs://{cases}",
                "--member",
                f"serviceAccount:{emails[name]}",
                "--role",
                "roles/storage.objectUser",
            )
        run(
            "gcloud",
            "storage",
            "buckets",
            "add-iam-policy-binding",
            f"gs://{builds}",
            "--member",
            f"serviceAccount:{emails['build']}",
            "--role",
            "roles/storage.objectViewer",
        )
        run(
            "gcloud",
            "projects",
            "add-iam-policy-binding",
            project,
            "--member",
            f"serviceAccount:{emails['api']}",
            "--role",
            "roles/cloudtasks.enqueuer",
            "--condition=None",
        )
        run(
            "gcloud",
            "iam",
            "service-accounts",
            "add-iam-policy-binding",
            emails["tasks"],
            "--project",
            project,
            "--member",
            f"serviceAccount:{emails['api']}",
            "--role",
            "roles/iam.serviceAccountUser",
        )
        queue_flags = [
            "--project",
            project,
            "--location",
            region,
            "--max-concurrent-dispatches=1",
            "--max-dispatches-per-second=1",
            "--max-attempts=3",
            "--min-backoff=30s",
            "--max-backoff=300s",
        ]
        queue_action = (
            "update"
            if exists(
                "gcloud",
                "tasks",
                "queues",
                "describe",
                "lastrada-analysis",
                "--location",
                region,
                "--project",
                project,
            )
            else "create"
        )
        run("gcloud", "tasks", "queues", queue_action, "lastrada-analysis", *queue_flags)
        image = artifacts + ":" + build_source["commit"][:12]
        build = {
            "steps": [
                {
                    "name": "gcr.io/cloud-builders/docker",
                    "env": ["DOCKER_BUILDKIT=1"],
                    "args": ["build", "-f", "deploy/Dockerfile", "-t", image, "."],
                }
            ],
            "images": [image],
            "timeout": "1800s",
            "serviceAccount": f"projects/{project}/serviceAccounts/{emails['build']}",
            "options": {"logging": "CLOUD_LOGGING_ONLY"},
        }
        run(
            "gcloud",
            "builds",
            "submit",
            ".",
            "--project",
            project,
            "--config",
            write_json(temp / "build.json", build),
            "--gcs-source-staging-dir",
            f"gs://{builds}/source",
        )
        common = {
            "GOOGLE_CLOUD_PROJECT": project,
            "LASTRADA_BUILD_SHA": build_source["commit"],
            "LASTRADA_BUILD_BRANCH": build_source["branch"],
            "LASTRADA_CASE_BUCKET": cases,
            "LASTRADA_REGION": region,
            "LASTRADA_ACCESS": "google",
            "LASTRADA_ORIGINS": ",".join(origins),
            "LASTRADA_USER_DAILY_JOBS": "3",
            "LASTRADA_DAILY_JOBS": "20",
        }
        for service in ("lastrada-api", "lastrada-worker"):
            if exists(
                "gcloud",
                "run",
                "services",
                "describe",
                service,
                "--project",
                project,
                "--region",
                region,
            ):
                metadata = json.loads(
                    run(
                        "gcloud",
                        "run",
                        "services",
                        "describe",
                        service,
                        "--project",
                        project,
                        "--region",
                        region,
                        "--format=json",
                        capture=True,
                    )
                )
                if (
                    metadata.get("metadata", {}).get("labels", {}).get("lastrada-managed")
                    != "firebase-web"
                ):
                    raise SystemExit(
                        "Refusing to overwrite an existing unmarked service: " + service
                    )
        worker_env = {
            **common,
            "LASTRADA_SERVICE_MODE": "worker",
            "LASTRADA_SAMPLEID_CHECKPOINT_URL": model_url,
        }
        run(
            "gcloud",
            "run",
            "deploy",
            "lastrada-worker",
            "--project",
            project,
            "--region",
            region,
            "--image",
            image,
            "--labels=lastrada-managed=firebase-web",
            "--service-account",
            emails["worker"],
            "--no-allow-unauthenticated",
            "--cpu=2",
            "--memory=4Gi",
            "--concurrency=1",
            "--min-instances=0",
            "--max-instances=1",
            "--timeout=1800",
            "--env-vars-file",
            write_json(temp / "worker.json", worker_env),
            "--quiet",
        )
        run(
            "gcloud",
            "run",
            "services",
            "add-iam-policy-binding",
            "lastrada-worker",
            "--project",
            project,
            "--region",
            region,
            "--member",
            f"serviceAccount:{emails['tasks']}",
            "--role",
            "roles/run.invoker",
        )
        worker_url = run(
            "gcloud",
            "run",
            "services",
            "describe",
            "lastrada-worker",
            "--project",
            project,
            "--region",
            region,
            "--format=value(status.url)",
            capture=True,
        )
        api_env = {
            **common,
            "LASTRADA_SERVICE_MODE": "api",
            "LASTRADA_WORKER_URL": worker_url,
            "LASTRADA_TASK_ACCOUNT": emails["tasks"],
        }
        run(
            "gcloud",
            "run",
            "deploy",
            "lastrada-api",
            "--project",
            project,
            "--region",
            region,
            "--image",
            image,
            "--labels=lastrada-managed=firebase-web",
            "--service-account",
            emails["api"],
            "--allow-unauthenticated",
            "--cpu=1",
            "--memory=1Gi",
            "--concurrency=20",
            "--min-instances=0",
            "--max-instances=2",
            "--timeout=300",
            "--env-vars-file",
            write_json(temp / "api.json", api_env),
            "--quiet",
        )
        api_url = run(
            "gcloud",
            "run",
            "services",
            "describe",
            "lastrada-api",
            "--project",
            project,
            "--region",
            region,
            "--format=value(status.url)",
            capture=True,
        )
    write_json(
        ROOT / "web/public/config.json",
        {"firebase": firebase_config, "apiBase": api_url, "build": build_source},
    )
    # An explicit site prevents overwriting an implicitly selected default site.
    hosting_config = json.loads((ROOT / "firebase.json").read_text())
    hosting_config["hosting"]["site"] = hosting_site
    hosting_config["hosting"]["public"] = str(ROOT / "web/public")
    with tempfile.TemporaryDirectory() as directory:
        config_path = write_json(Path(directory) / "firebase.json", hosting_config)
        run(*firebase, "deploy", "--only", "hosting", "--project", project, "--config", config_path)
    print(
        "Deployment commands completed. Verify Google sign-in and a generated-audio case before client use."
    )
    print(
        f"Enable/check Google sign-in at https://console.firebase.google.com/project/{project}/authentication/providers"
    )
    print("API deployment:", api_url)
    print(
        "Open the Hosting URL printed by Firebase. This script does not claim a successful end-to-end analysis."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default="lastrada-64bab")
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--model-url", default=DEFAULT_MODEL)
    parser.add_argument(
        "--expected-branch",
        help="Require this checkout branch; apply defaults to the profile branch",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve-resources", action="store_true")
    parser.add_argument("--firebase-app-id")
    parser.add_argument("--hosting-site")
    parser.add_argument(
        "--confirm-hosting", help="Explicit approval to replace content at PROJECT/SITE"
    )
    parser.add_argument(
        "--approve-existing-queue", help="Exact reviewed queue resource name, if it already exists"
    )
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", args.project) or not re.fullmatch(
        r"[a-z]+-[a-z]+\d+", args.region
    ):
        parser.error("Use a valid Google project ID and region")
    if not args.model_url.startswith("https://"):
        parser.error("Use an HTTPS model URL")
    print(json.dumps(plan(args.project, args.region), indent=2))
    if args.apply:
        if not args.approve_resources:
            parser.error(
                "Review the resource/cost/IAM plan and add --approve-resources only after approval"
            )
        apply(
            args.project,
            args.region,
            args.model_url,
            app_id=args.firebase_app_id,
            hosting_site=args.hosting_site,
            confirm_hosting=args.confirm_hosting,
            approved_queue=args.approve_existing_queue,
            expected_branch=args.expected_branch,
        )
    else:
        print(json.dumps({"build_source": source_identity(args.expected_branch)}, indent=2))
        print(
            "PLAN ONLY: no cloud commands executed. Deployment needs authenticated project access and explicit resource approval."
        )


if __name__ == "__main__":
    main()
