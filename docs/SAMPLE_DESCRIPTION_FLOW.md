# Prefilled recording-sample flow

The Firebase interface on `local/stem-fast` now uses six steps: tracks, finding
the sample, describing the sound, placement, draft review, and download.
Supported recording matches go directly to **Does this describe your sample?**
There is no separate timestamp confirmation or replay/re-singing question.
The Streamlit interface and classic review API remain compatible.

## Prefill and confirmation

All five sound answers contain editable values. Instrument descriptions use
current-model, current-version evidence for the matched moments. Unidentified
instruments stay explicitly unresolved. Sample-level source sound estimates are
identified as source sounds; surrounding-context estimates are not presented as
sampled instruments. Checked portions remain available per occurrence.

Method and repetition are suggested from the recording match and timing pattern.
Musical role is a proposal to confirm or change, not an instrument-model finding.
Lyrics are prefilled as **Not assessed — add any reused lyrics**: there is no
transcription model, and this value is not saved as verified lyrics or a claim
that no lyrics were used. An unchanged or empty lyrics answer produces an export
limitation. Generic **matched passages** supplies a placement answer without
inventing verse or chorus names; timing-based intro/outro/throughout proposals
remain editable.

The primary actions explicitly confirm the description and then the placement.
Automatic instrument checks can update untouched answers while the description
is open. Deliberate edits, empty lyrics, and confirmed descriptions survive later
results and reloads. If an instrument job is already running, saving waits for
it with a visible message; no extra confirmation is needed after it finishes.
The final document still requires explicit review before export.

The optional **Sample matches and instruments** panel contains read-only timings,
playback, per-moment evidence, and ending uncertainty. It is not a required step.

## Evidence and saved records

The server owns automatic times. Paired direct-waveform, full-mix DTW, and
stem-assisted DTW localizations qualify for the new flow. Coarse retrieval windows
and PF-NMF activity alone do not. A case without a supported match displays an
explicit inability to identify the sample and a way to try another pair.
This is a conservative eligibility rule, not a new detector or an accuracy claim.

Description approval does not relabel timestamps as human-verified. Their raw
source, candidate status and ending cues are retained. Corrected paths record
`timing_source: automated`; the export calls these estimated timings and separates
them from the reviewed description. Raw analysis evidence stays intact.

New web cases request recording analysis only. Older records remain readable:
previously reviewed timings and explicit composition reviews are preserved;
unreviewed composition paths are marked not requested in the new corrected
document, not declared absent. `workflow` defaults to `classic` for old records
and callers. Exact description answers are saved separately so a deliberately
cleared field is not refilled on reload. A frontend talking to an older API
retains its classic flow until the services are updated together.

## Validation and limits

Local validation uses real Python review/document logic with simulated Google
identity, uploads, and job transport. It does not establish live sign-in, hosted
inference, or musical accuracy.

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
node --check web/public/app.js
PYTHON=.venv/bin/python npm test --prefix web
PYTHON=.venv/bin/python npm run test:instruments --prefix web
```

Seven new browser scenarios cover filled answers, unresolved instruments, no
supported match, saved edits/reload, background instrument updates, confirming
during a running check, and a supported subset of mixed raw candidates. Existing
classic-flow and instrument scenarios remain in the suite. API tests cover saved
analysis validation, explicit description approval and JSON/HTML/text exports.

A read-only eligibility check on six older private saved song analyses found
supported localizations in two cases (one and three intervals respectively).
The other four contained only coarse candidates and would abstain. These were
not rerun through current inference; this is not a rescore of the historical
3/22 evaluation or evidence of improved real-song accuracy. No client audio is
tracked or uploaded as part of this change.

Deployment requires the API, worker and Hosting together. Use the existing
`deploy/redeploy.py` inspect/apply process with the exact commit after required CI
passes; see the final section of [STEM_FAST_FIREBASE.md](STEM_FAST_FIREBASE.md).
Do not use the older provisioning commands for an existing installation.
