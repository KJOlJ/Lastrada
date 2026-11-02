# Firebase web deployment

The user has since enabled Blaze billing and deployed the existing app. Updates
use that existing project and the explicitly selected site. The resource limits
below still apply. See [the local $0 fallback](ZERO_COST_LOCAL.md) for local use,
and [workflow validation](WORKFLOW_VALIDATION.md) for per-moment instrument updates.

This is a new Firebase Hosting UI and Python Cloud Run backend. It does not run
Streamlit. The existing Streamlit app and deployment remain available while the
new deployment is validated. Target project: `lastrada-64bab`.

## What is ready

The browser uploads recordings directly to private Cloud Storage, queues analysis,
and polls saved results. Google sign-in is required. Every case belongs to one
Firebase user; another signed-in user cannot retrieve it. Both recorded-audio
and replayed-music checks run by default. Review accepts detected timestamps or
allows corrections, skips a use marked absent, and requires enough musical
context before exporting a Nature of Use document. Timing suggests placement;
it does not establish chorus/verse labels, instruments, or legal rights.

Demucs runs only when requested, on a short paired probe for each eligible
sample occurrence. It uses four-stem `htdemucs`, four-second processing segments
and one CPU thread. Requests stop after ten minutes or fifty new comparisons;
completed rows and exact separated crops are reused. Ordinary browser inputs do
not rerun Python analysis. See the workflow guide for measured local performance.

## Resources requiring approval

Run `python deploy/bootstrap.py` to print the plan without cloud operations.
The proposed region is `us-central1`:

| Resource | Proposed limit |
| --- | --- |
| API Cloud Run service | 1 CPU, 1 GiB, zero minimum / two maximum instances, concurrency 20 |
| Private worker Cloud Run service | 2 CPUs, 4 GiB, zero minimum / one maximum instance, concurrency 1 |
| Analysis queue | One concurrent dispatch, up to three attempts |
| Worker execution | 25-minute subprocess cap, 30-minute request deadline |
| Application quotas | Three reservations/instrument requests per user; twenty globally per UTC day |
| Private case bucket | Seven-day lifecycle cleanup |
| Private build bucket | One-day lifecycle cleanup |
| Artifact Registry | Container image repository |
| Service accounts | `lastrada-api`, `lastrada-worker`, `lastrada-tasks`, `lastrada-build` |

The script grants bucket-scoped object access, queue enqueue permission,
permission for the API to act as the task account, task-account-only invocation
of the private worker, and build repository/logging permissions. It creates no
service-account keys. It refuses to enable billing and requires billing already
linked to the project. It refuses to change unmarked existing case/build buckets,
service accounts, Cloud Run services, or Artifact Registry repositories. Existing
queues require approval of their exact resource name. Firebase app and Hosting
site selection are mandatory; replacing the selected site requires an explicit
`PROJECT/SITE` confirmation before provisioning starts.

Cloud Run, Cloud Build, Artifact Registry, Tasks, Storage and network usage may
incur charges. Zero minimum instances avoids idle runtime allocation. These
limits bound workload, **not a dollar budget**: retries, builds, stored images
and downloads also count. No credible monthly estimate exists until real model
runtime and usage are measured. Review current Google Cloud prices and configure
budget alerts before applying; alerts do not impose a hard spending cap.

## Deploy from your authenticated Google Cloud Shell

No usable Google Cloud credentials are available in the Codex workspace. Use
standard Google sign-in in Cloud Shell; do not paste passwords, tokens, or keys
into chat.

1. Open Cloud Shell from the project console and confirm the signed-in account
   can administer this project. Clone this repository and check out
   `feat/firebase-web`.
2. Run the read-only plan:

   ```bash
   python deploy/bootstrap.py --project lastrada-64bab
   ```

3. Inspect Firebase Console → Project settings → Your apps for the exact WEB
   app ID, and Hosting for the intended existing site ID. Select them explicitly;
   the script does not create an app or choose the first existing app. Review
   existing Hosting content: the following command replaces that site's content.
   After the resource/IAM/cost plan and exact Hosting target have been approved,
   substitute those IDs and run:

   ```bash
   python deploy/bootstrap.py --project lastrada-64bab --apply --approve-resources \
     --firebase-app-id YOUR_WEB_APP_ID --hosting-site YOUR_SITE_ID \
     --confirm-hosting lastrada-64bab/YOUR_SITE_ID
   ```

   This enables required APIs, creates the bounded resources, builds/deploys the
   container, and deploys Hosting. Firebase CLI may request its own OAuth login.
   If billing is disabled, the script stops without changing it. Resolve access
   errors before retrying; inspect resources after an interrupted deployment.
   If `lastrada-analysis` already exists, inspect its ownership, pending jobs and
   settings before approving adoption with
   `--approve-existing-queue projects/lastrada-64bab/locations/us-central1/queues/lastrada-analysis`.
   An unmarked existing Artifact Registry repository is blocked rather than adopted.
   App, site, repository and queue checks run before cloud provisioning; login
   uses standard interactive OAuth. A missing API or denied inspection also stops
   the preflight rather than treating the resource as absent.
4. In Firebase Console → Authentication → Sign-in method, enable **Google** and
   choose the support email. Check that the deployed Hosting domain appears in
   Authentication → Settings → Authorized domains. Anyone with a verified Google
   sign-in can use the app; recordings remain private to their account.
5. Open the Hosting URL printed by Firebase CLI. Sign in, upload a short test
   pair, inspect timestamps, confirm one use and reject any absent use, complete
   review, and download the document. Verify another account cannot access the
   case. Request the optional instrument check separately.
6. Inspect Cloud Run worker logs for successful Sony checkpoint loading and
   analysis. Checkpoint source is
   `https://storage.googleapis.com/lastrada-model-files-sri/sampleid-best.ckpt`;
   the worker checks its expected SHA-256. A PF-NMF fallback warning means Sony
   inference has **not** been established. Real weights may need additional
   worker-memory/runtime tuning based on measurements.

The generated `web/public/config.json` is ignored by Git. Firebase client config
is public app configuration; private access is enforced by backend token checks
and IAM, not by hiding that config. Cloud storage is not publicly readable.
Lifecycle cleanup is asynchronous, not an exact seven-day deletion deadline.

## Verification performed in Codex

- 120 Python tests passed, including ownership isolation, Google-provider checks,
  quotas, timestamp/review validation, export gating and mocked provisioning.
- Browser test passed upload → timestamp confirmation → review → HTML download
  and reload/resume. Google identity and cloud transport were mocked; the real
  Python review/document rules ran.
- Production Docker image built with verified signed Debian packages and TLS.
  Imports passed for CPU Torch and Demucs; Streamlit is absent. Container health
  returned 200, unauthenticated case access 401, and public worker route 404.
- Ruff and JavaScript syntax checks passed. Deployment plan was inspected.

These checks do not verify live Firebase sign-in, deployed IAM, hosted throughput,
or cloud cost. A separate local pretrained-model run on the private uploaded pair
is documented in the workflow guide. No cloud resources were provisioned by this
workspace; the user deployed the existing app from Cloud Shell.

For local browser verification:

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
node --check web/public/app.js
npm ci --prefix web
(cd web && npx playwright install chromium)
PYTHON=.venv/bin/python npm test --prefix web
```
