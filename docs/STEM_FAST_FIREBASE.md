# Deploy local/stem-fast with Firebase UI and Google sign-in

The deployment source for this test is **`local/stem-fast`**. Its original
application commit is `a900f0a8582dae8ab062df400fc1d779fa53712e`. The branch now
includes the Firebase interface, private queued worker and review workflow from
`feat/firebase-web` (`ecb89a4053de6042ed97120ce00aab76dcea26ff`).

`feat/stem-assisted-main-flow` remains unchanged at
`2759ff23b71526ad3c72959bdff66c94ab328ae6`; it was the base of the earlier Firebase
branch. The two analysis branches are distinct. This test does not deploy the
Streamlit interface or use the separate `deploy/cloud-run` workflow, which has a
public Streamlit service and a larger resource allocation.

## Current evidence update

See [INSTRUMENT_EVIDENCE.md](INSTRUMENT_EVIDENCE.md) for the current v2 behavior:
short clips receive sample/context sound estimates, repeated source intervals
share a source description, and DTW uses content and slope safeguards. The
historical validation measurements below describe the earlier integration.

The subsequently deployed grouped frontend is on `lastrada-alt.web.app` (Firebase
web app `1:471058014767:web:9b99b922f532c81db5dcda`) and shares the API/worker with
the original site. Its existing origins and daily limits must be preserved when
updating the backend. The bootstrap commands below describe the original site
setup; do not use them blindly to update the alt site or reset its configuration.

## Effective workflow

- Firebase Hosting interface and verified Google sign-in remain in place.
- Sony SampleID and guarded full-mix DTW run first. The six-stem `htdemucs_6s`
  model then compares the top three paired candidates, as in the fast profile.
  It can refine a coarse Sony timing; existing waveform/full-mix refinements
  remain intact. The current pass uses the v2 content and slope safeguards.
- Those three comparisons are associated with their own timestamps. Instrument
  prefills exclude full-mix matches, cross-label spillover, moments under two
  seconds and extreme duration ratios. Guitar and piano estimates are available;
  no model suggestion is automatically expert-verified.
- Remaining moments, including short clips, are checked by the grouped interface in bounded batches (up to
  ten minutes, fifty comparisons, eight seconds per recording per probe). These
  additional checks retain the stricter 0.5–2x ratios and ±2-semitone search.
- Repeated source passages are summarized as loop groups without deleting raw
  timestamps. Grouping is a timing heuristic, not proof of a musical loop.
- Previously saved four-stem results remain in the analysis data; they do not
  count as six-stem checks or silently prefill new six-stem results. Human edits
  are retained. Start a new case for the full fast-profile analysis.

The cloud wrapper uses four-second Demucs processing segments, one separation
thread, and a 180-second timeout per crop. The existing worker stays at **2 CPUs,
4 GiB, minimum 0, maximum 1 instance, concurrency 1**, with the existing queue,
25-minute subprocess limit, private buckets and daily request quotas. No new
service accounts, permission expansion, or larger instances are part of this
update. Existing build/runtime/storage charges still apply.

## Run in your authenticated Cloud Shell

Use a fresh checkout to keep an existing checkout's local changes intact:

```bash
cd ~
git clone --branch local/stem-fast --single-branch \
  https://github.com/tankr98/Lastrada.git Lastrada-firebase-stem-fast
cd Lastrada-firebase-stem-fast
git rev-parse HEAD
python deploy/bootstrap.py --expected-branch local/stem-fast
```

If that directory already exists, enter it, verify `git branch --show-current`
prints `local/stem-fast`, and run `git pull --ff-only origin local/stem-fast`.
The plan prints the branch, full commit, analysis profile and resource limits.
Deploy the already selected project/app/site with:

```bash
python deploy/bootstrap.py --project lastrada-64bab \
  --expected-branch local/stem-fast --apply --approve-resources \
  --firebase-app-id 1:471058014767:web:2d055ff7689d348fb5dcda \
  --hosting-site lastrada-64bab \
  --confirm-hosting lastrada-64bab/lastrada-64bab \
  --approve-existing-queue projects/lastrada-64bab/locations/us-central1/queues/lastrada-analysis
```

The script refuses the wrong branch or an uncommitted working tree before cloud
access. It tags the container with the source commit and writes the same identity
to the API/worker environment and frontend configuration. It updates the existing
API, worker and Hosting site, so all three must finish before testing.

After deployment, open the app's footer **App version**. It must show
`local/stem-fast`, the commit printed above, and `stem-fast`. The API `/health`
response exposes the same branch/commit/profile, plus the Cloud Run revision.
Sign in with Google, upload a fresh case, verify loop groups and instrument rows,
then complete review and download. A reported model fallback is not a successful
Sony/six-stem inference check.

The Codex workspace has no `gcloud` installation or authenticated project session.
The user's Cloud Shell sign-in is separate. Public Hosting inspection from this
workspace is also blocked by its network proxy (HTTP 403). Do not paste tokens or
service-account keys into chat. Live deployment verification must be performed
from authorized Cloud Shell/browser access.

## Verification of this integration

The unmodified fast branch passed 92 Python tests and its local launcher opened.
The integrated Firebase version also runs the existing ownership/sign-in/quota,
review/export, per-moment checks and loop-grouping tests. Browser scenarios cover
success, failures, quota limits, empty/unknown-source results, editing/rechecking
timestamps, preserving descriptions and resetting a sample. Google identity and
cloud transport are simulated; Python review/document validation is real.

A private real-audio run on the supplied pair completed Sony inference, full-mix
DTW and all three six-stem comparisons under a **2 CPU / 4 GiB Docker limit**:

- Full analysis: **618.6 seconds** (Sony 216.1s, localization 88.9s, stems 312.9s).
- Peak container memory: **2.67 GiB**, with no out-of-memory termination.
- Fifty raw candidate moments, seventeen repeated-passage groups, three initial
  stem comparisons; one coarse timing refined by stem-assisted DTW.
- Those three resulting moments were too short for dependable automatic sound
  prefills. Thirty-four moments were marked too short and sixteen remained
  eligible for an optional check. This demonstrates execution, not instrument
  accuracy; it must not be reported as three verified sampled instruments.

Models were already downloaded for that measurement. It used the existing
production dependency image with the integrated source mounted read-only. It is
not a hosted latency, cold-download or billing measurement. The separate clean
image build and optional-check verification are reported in the task checkpoint.

Final local checks: **131 Python tests**, Ruff, JavaScript syntax, synthetic
validation, eight instrument browser scenarios and the real-result browser flow
through HTML download passed. The production Dockerfile built successfully after
resolving the configured proxy hostname in the build container; TLS and signed
Debian package verification remained enabled. The resulting image returned
health/profile metadata, rejected unsigned case access (401), and did not expose
the private worker route on the API (404).

One additional six-stem per-moment comparison in that freshly built image took
**78.4 seconds** with **1.23 GiB** peak container memory. It completed but found no
accepted instrument match; no sound description was invented. Saved progress,
original timings and prior review were preserved. The remaining optional moments
were not exhaustively rechecked in this validation.
