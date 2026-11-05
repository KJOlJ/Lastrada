# Timestamp regression and corpus evaluation

Work on `local/stem-fast`. The deployed comparison baseline for this investigation
is `48cd02178062408fbdc778ebde040fad56da5a92`. Keep predictions from that version
separate from candidate outputs; never replace existing cases or reference data.
Changes to timing evidence do not require changes to the intake, grouped sample
review, instrument descriptions, editing, or document export workflow.

## Skipped-window clock correction

SampleID omits windows whose audio is effectively silent. The old grouping code
fit progression and gaps using positions in the resulting embedding arrays. That
compresses the time axis: three matches at 10, 40, and 70 seconds can look like
three consecutive matches. It can also combine separate occurrences across a
silent gap or accept an implausible source-to-new-work speed relationship.

Grouping now uses each window's actual start time. Gap limits use the configured
new-work hop, and alignment tolerance uses the source hop. Cache reads preserve
that hop without downloading models or recomputing embeddings. Candidate score
thresholds, minimum support, DTW settings, and user-facing result schemas are
unchanged. Invalid or unordered timestamp metadata is rejected.

Regression checks include continuous matches, separate occurrences across
silence, source-only gaps, isolated matches, non-default hops, and existing cache
compatibility:

```bash
.venv/bin/python -m pytest tests/test_sampleid.py -q
```

Three gap scenarios failed on the deployed baseline and passed with this fix.
A separate replay of the six previously uploaded pairs reused their original
pretrained Sony embeddings and compared all candidate boundaries: all 245
candidate intervals were identical. That replay is a compatibility check, not an
accuracy improvement on historical recordings. Its input hashes, cache identities,
baseline source and comparison results remain under ignored `outputs/private/`.

## Direct-copy boundary correction

The direct waveform stage previously stopped at its first two-second comparison,
even for longer copied passages. It also searched only one second around a Sony
candidate, although the default embedding window is five seconds long. The main
pipeline now searches within that existing window length, validates a distinctive
two-second anchor, and extends through consecutive half-second blocks that pass
the existing 0.75 correlation threshold. An unmatched block stops the extension.
The result stays within the candidate source range and the bounded new-work
search region, and remains an unverified candidate requiring listening review.

Near-equal alternative lags outside a 100 ms neighborhood cause abstention rather
than an arbitrary precise start. Correlation uses float64 and excludes zero-energy
windows: FFT roundoff in silence previously could be divided by a tiny denominator
and create a false high score. The Sony and DTW thresholds are unchanged. No new
interface controls, model downloads, resource settings, or deployment are needed
to evaluate this code locally.

Controlled copies from the already available recordings were compared with the
deployed baseline. One set used six original recordings; additional validation
used the six newer recordings, different source offsets and durations, stronger
background mixtures, and 24 MP3 round trips. All input and prediction manifests
remain private. These tests assess direct waveform refinement, not full-pipeline
accuracy on the historical pairs:

| Check | Baseline | Candidate |
|---|---:|---:|
| Development copies (60): mean temporal IoU | 0.567 | 0.950 |
| Development: median end error | 2.00 s | 0.00 s |
| Development: refined cases | 60/60 | 60/60 |
| Additional validation copies (72): mean temporal IoU | 0.382 | 0.783 |
| Additional validation: median end error | 3.35 s | 0.25 s |
| Additional validation: refined cases | 63/72 | 59/72 |
| Additional validation: 90th percentile end error | 8.02 s | 8.02 s |
| Noise/ambiguity controls per set: precise refinements | 7/13 | 0/13 |

IoU and boundary errors include every positive case, including coarse fallbacks.
The wider ambiguity check reduces refinement coverage on four validation cases;
worst-case performance remains poor. Short copies and transformed recordings
still need further work. A retained coarse candidate is not a negative detection.

A separate Sony-to-refinement check used actual pretrained inference on six
manufactured six-second copies. With the bounded window search, all six included
a candidate with correct paired boundaries. This best-candidate result does not
measure precision across other returned rows. Twelve independent-noise/reversal
controls produced no direct or DTW refinements in either version. Replaying all
245 Sony proposals from the six actual song pairs through direct refinement
produced identical outputs before and after the change; those commercial-song
timings have not been shown to improve.

One manufactured copy also completed the full main analysis, including PF-NMF,
real Sony inference and the initial six-stem stage, for both versions in separate
network-disabled containers capped at 2 CPUs / 4 GiB. Best paired overlap improved
from 0.667 to 1.000. Baseline runtime/peak memory were 146.9 s / 2.21 GiB; candidate
runtime/peak memory were 181.0 s / 2.16 GiB. Both used separate analysis caches and
the same installed model files. This single local run shows compatibility with
the existing resource limits, not a hosted latency or cost forecast; the candidate
was slower in this example. It does not establish instrument-label accuracy.
The resulting analysis also passed the browser review-to-document flow with
simulated Google identity, cloud transport and reviewer answers. The full local
suite passed 185 Python tests, Ruff, the synthetic smoke check, the standard web
checks and nine instrument scenarios. Those checks do not verify a live deployment.

The available six pairs do not overlap the original 22-pair workbook. Four have
written reference intervals, but all four have recording-version warnings and
none has a complete, validated interval annotation. The original 3/22 number is
an automated zero-tolerance paired-start containment check, not a complete human
timestamp accuracy grade. It has not been rescored here.

## Short-copy follow-up

An independent reconstruction of `cbba3ea` reported better overlap on manufactured
corpus controls, but 1.25-1.5 second copies could still inherit the entire
two-second anchor. The follow-up preserves that commit's lag search, acceptance
threshold and ambiguity check. When the existing half-second extension finds no
continuation, it checks the anchor backwards in quarter-second blocks and trims
an unsupported ending only if the remaining prefix still passes the same 0.75
correlation threshold. At least half a second must remain. Accepted lags and
candidate count are unchanged; this can only shorten an existing direct match.
Matches extended beyond the anchor are unchanged. No UI, schema, resource,
deployment or instrument-classification setting changes are involved.

Checking every anchor block from the start was rejected: quiet/obscured interior
blocks truncated real longer copies, reducing mean paired IoU from 0.652 to
0.603 on 576 exploratory controls. The terminal-only check raised it to 0.698
with the same 400 refinements, but worsened overlap on 23 cases. Both attempts
and predictions are retained under ignored `outputs/private/short-copy-2026-11-05/`.

The terminal-only code was then frozen and evaluated on fresh source/background
passages within the same 12 recordings, with different insertion offsets and
noise seeds. This is a follow-up within known recordings, not an independent
recording test or real-pair evaluation. Some cases include MP3 re-encoding.
The baseline below is `cbba3ea`, not the deployed application:

| Frozen follow-up check | `cbba3ea` | Short-copy candidate |
|---|---:|---:|
| 396 copies: mean paired IoU | 0.696 | 0.739 |
| Refined copies | 290/396 | 290/396 |
| Median worst endpoint error | 0.25 s | 0.10 s |
| 90th percentile / maximum endpoint error | 7.83 / 8.18 s | 7.83 / 8.18 s |
| 1.25-second copies (36): mean paired IoU | 0.314 | 0.450 |
| 1.25-second copies: refinements | 13/36 | 13/36 |
| 1.5-second copies (36): mean paired IoU | 0.620 | 0.815 |
| 1.5-second copies: refinements | 28/36 | 28/36 |
| Noise, reversal, silence, ambiguity and tone controls: refinements | 0/50 | 0/50 |

Paired IoU is the lesser of source/new interval IoU; endpoint error is the largest
absolute error across their four boundaries. Both include coarse fallbacks.
All 41 accepted 1.25-1.5-second cases had correct boundaries in this follow-up,
but 31 retained coarse intervals. The median error for 1.25-second cases therefore
remained 7.64 seconds. Twelve cases lost overlap: eleven 1.9-second copies changed
from a 0.10-second overestimate to a 0.15-second underestimate, and one noisy
two-second copy lost its final 0.25 seconds. Quiet endings can be underestimated;
quarter-second checks do not establish sample-accurate boundaries. The original
anchor gate still misses many short or transformed copies, and coarse false
candidates are not suppressed. Twelve other-recording distractors also produced
no refinements; they are unannotated and are not counted as known negatives.

All 245 existing Sony proposals from the six actual pairs remained identical
through direct refinement. The 199 Python tests, Ruff and synthetic smoke passed;
six short-copy regression cases fail on `cbba3ea` and pass with this correction.
The standard browser workflow and all nine instrument scenarios also passed,
including the short-context path, using simulated identity, API transport and
instrument evidence with real Python review validation. No model inference or
live deployment was rerun for this follow-up.
The full corpus is still unavailable in this executor, and 3/22 remains unrescored.

## Obscured-tail uncertainty

Independent follow-up controls found that `ed1981e` can trim a genuinely copied
ending when it is attenuated and obscured by another sound. A weak correlation
does not establish that the copied sound stopped. The next change therefore
preserves numeric estimates and acceptance decisions while adding `end_review`
to every shortened anchor: the untrimmed paired anchor endpoints and the reason
`quiet_or_obscured_tail`. These are listening reference points, not a confidence
interval, verified continuation, or a guarantee that the true end falls inside
that range.
Unchanged long matches, clean anchors and rejected candidates get no cue.

The Firebase listening table marks affected endpoints as approximate and says
"Ending unclear" with a reference point in each track. It explicitly says audio
may continue beyond those points and asks the reviewer to listen for the actual
ending. The cue stays visible in the grouped relationship table, and numeric data
attributes preserve grouping and instrument-evidence matching. Existing time confirmation resolves
the cue; edits retain it until that confirmation, including edits to a start only
or to an end beyond the reference point. Editing again resets confirmation and
restores the cue. No extra confirmation step is added.
Raw automated JSON retains the note separately from reviewed times, and the
spectral hover explains it too. Legacy intervals without the field still load.

The local investigation used 360 matched tail cases from the same 12 recordings:
two-second copies, final 0.25/0.5-second tails, gains 1/0.1/0.03/0.01/0, and three
levels of seeded independent background noise. Gain zero represents a genuinely
shorter copy; nonzero gains retain a real copied tail. A provisional 0.1 suffix
correlation guard would preserve only 60 of 128 obscured tails that were trimmed.
A looser 0.05 guard would preserve 90, but also retain three genuinely absent
tails. Neither guard was added to production code.

| Cue check versus `ed1981e` | Result |
|---|---:|
| Numeric predictions and acceptance decisions unchanged | 360/360 |
| Accepted matches | 338/360 in both versions |
| Shortened obscured tails flagged | 128/128 |
| Genuine short copies also flagged | 66/66 accepted |
| Clean full-copy cases with a cue | 0/72 |
| Additional noise/silence/reversal/ambiguous-lag controls refined | 0/48 in both versions |

This makes uncertainty explicit; it does not improve point-estimate accuracy or
automatically recover an obscured tail. Short-copy gains remain numerically
unchanged. The cost is a listening note even when the short endpoint is correct.
The tests are manufactured controls within known recordings, not a new historical
accuracy score. The expanded corpus remains unavailable here and 3/22 is unrescored.

Validation passed 211 Python tests, Ruff, JavaScript syntax, synthetic smoke,
the standard browser suite, both ending accept/edit flows and all nine instrument
scenarios. Browser identity, cloud transport and instrument evidence are simulated;
Python review and document validation are real. No new model inference or live
deployment was performed. No changes have been pushed or deployed.

### Ending review corrections

Independent review of `545c672` found that editing a start removed an unresolved
ending warning, that the listening wording could imply a sufficient stopping
point, and that an overlapping uncued row could become the displayed
representative and lose the derivative approximate marker. The corrections above
address the first two issues. For the third, an occurrence now retains its
approximate marker when any of its contributing rows has an unresolved ending.
Separate uncued occurrences stay unmarked. Representative timestamps, grouping,
and raw row evidence are unchanged; the note is still shown once per distinct
warning in the existing summary.

The mixed-row regression failed before the fix and passed afterward. Browser
coverage exercises start-only edits, unchanged and extended end edits, listening
confirmation, editing after confirmation, returning to pending review, overlapping
mixed cues, and reviewed JSON/document exports. The independent evaluator reported
10,550 unchanged numeric outputs for `545c672` and all 829 previously identified
obscured tails flagged; those larger-corpus checks were not run in this executor.
This follow-up changes review behavior and wording only, not numeric predictions.
The warning remains a listening cue rather than an uncertainty interval.

Validation passed 211 Python tests, Ruff, JavaScript syntax, synthetic smoke, the
standard browser suite, all four ending-review scenarios through HTML and JSON
downloads, and all nine instrument scenarios. Identity, cloud transport and
instrument evidence were simulated; Python review/export validation was real.
No new model inference, live Firebase validation, push or deployment was performed.

### Reopening saved reviews

The save/reload/edit regression reproduced a remaining gap in `f287bb4`: confirmed
rows correctly cleared their active warning, but reloading also lost the context
needed to restore it on a later edit. Reviewed intervals now retain the optional
`ending_review_context` separately from `end_review`. Confirmation still clears
the active warning and leaves the reviewed timestamps unchanged. The form restores
the retained context when loaded, hides it while confirmed, and shows it again
when the reviewer reopens or edits the times. This also works after an edited end
has passed the suggested listening point. Raw detector evidence is preserved.

Records without the new field remain valid. For legacy saved rows, the form can
recover a cue from an exact match of all four timestamps to the original detector
rows, provided those rows agree on the cue. It does not infer provenance from row
order, partial overlap or proximity. Older edited rows that no longer exactly
match, or have conflicting matching evidence, cannot safely recover a cue; their
raw evidence remains available. New saves retain recovered context for later use.
Rows without ending evidence remain unchanged. No new user action is required.

Validation passed 212 Python tests, Ruff, JavaScript syntax, synthetic smoke,
the standard browser suite with five save/reload/edit scenarios, legacy matching
and ambiguity checks, and all nine instrument scenarios. The regression failed
on `f287bb4` before the fix. HTML/JSON exports retain reviewed timestamps and
separate raw evidence; Python serialization tests cover a second save after
editing beyond both reference points. This is a persistence correction, with no
new numerical predictions, model inference, deployment or historical rescore.

## Instrument probe validity and resource bounds

Independent review found two downstream interactions with the extended/shortened
direct matches. First, a 1.5-second cued interval expanded to a four-second
instrument context crop while retaining the original ending cue. That made the
saved probe violate the interval invariant and caused result reads to return
HTTP 400, including after a failed separation. The regression reproduced both
outcomes through the actual queued worker and API persistence path. Derived
context probes now clear their own review metadata and validate before use; the
sample interval, ending cue and saved listening context are preserved.

Second, an identical 600-second input can yield a valid full-length direct match,
which was passed unbounded into initial stem separation and quadratic DTW. The
old call boundary was reproduced with a spy, without allocating the unsafe DTW
matrices. The reported out-of-memory concern is a calculated risk, not an observed
worker crash. Initial stem checks now use a centered paired fraction of at most
eight seconds in each track, preserving the paired duration ratio. The comparison
entry point also enforces this limit. Existing bounded padding remains in effect
(four seconds per side in the web profile). Full direct-waveform/full-mix matches
stay intact. A coarse interval longer than its probe also stays coarse; a partial
comparison cannot establish its full endpoints.

Stored instrument rows retain the full interval and the actual checked probe
separately. Bounded evidence is labeled as covering the checked portion, estimated
sound ranges stay within that portion, and the relationship table exposes the
checked times without changing the existing review steps. This limits instrument
claims to a short portion and does not prove instrumentation throughout a long
match. The numerical direct-waveform refiner itself is unchanged.

A deterministic 600-second identical-copy control retained 0–600 seconds in both
tracks. With separation replaced by a deterministic crop provider and real DTW,
the initial stage used eight-second probes, 16-second padded crops and observed
247×497 cost matrices. The corresponding cost/accumulated/back arrays together
occupy about 2 MiB, not a measurement of total worker or Demucs memory. No full
600-second Demucs/DTW inference or live deployment was run.

Validation passed 227 Python tests, Ruff, JavaScript syntax, synthetic smoke,
the standard browser suite (including automatic launch and five ending-review
flows), and ten instrument scenarios including bounded-portion display. The
worker/API regression validates every persisted snapshot and reads results,
saves review, and exports JSON/HTML/text after both successful and failed checks.
Previously saved invalid experimental probes are not migrated automatically;
the fix prevents new invalid probes while keeping the interval invariant strict.

## Repeated-source measurement scope

Independent review reproduced a scope-sharing error in `6bf852a`: two occurrences
referenced source 0–10 seconds, but their different playback durations produced
source probes of 1–9 and 3–7 seconds. Stabilization keyed only the full source times
and model, so either measurement could overwrite the other depending on row order.
Generated separated audio reproduced Bass + Guitar from the wider region leaking
into the narrower Guitar-only region, and the reverse loss of Bass when the narrow
row was processed first.

Sharing now also requires exact agreement on the measured start, end and
sample/context scope. These come from the presence measurements, since a short
sample can be measured inside a larger context probe. Different source intervals,
model versions or measured scopes retain independent estimates. Mixed-scope lists
are preserved without sharing. Matching measurements still reuse the first saved
description, including when a job resumes; new-mix estimates, alignment decisions
and prefills remain independent. The existing sound-details explanation now
states that sharing requires the same measured portion.

Regression coverage includes both processing orders, different probe lengths,
save/reload/resume, matching-scope reuse, and separate full, checked and measured
times in the browser. Generated stems test scope preservation, not Demucs
identification quality. No detector boundaries, thresholds, schema or stored
evidence version changed. Already overwritten experimental estimates cannot be
reconstructed from those saved estimates alone; this fix prevents further incorrect
sharing and does not migrate them or rescore the historical benchmark.

Validation passed 236 Python tests, Ruff, JavaScript syntax, the standard browser
suite and all eleven instrument scenarios. The new browser case checks distinct
measured scopes through the existing review and document-export flow. Nothing
was pushed or deployed.

## Larger corpus protocol

1. Place archives and the supplied manifest under ignored `data/private/` or an
   approved data directory outside the checkout. Never commit audio, private
   reports, downloaded models, credentials, or the source workbook.
2. Verify archive checksums against the manifest, inspect entries before
   extraction, reject paths outside the destination and symlinks, and preserve
   relative folders. Do not overwrite prior data or silently merge conflicting
   filenames. Count actual MP3 files and pair folders after extraction and report
   missing or corrupt entries separately.
3. Match folders and filenames to the workbook with `safe_audio_path` and run
   `scripts/audit_data.py`. Two available files per record are required for a
   runnable pair; a total file count does not establish the pair count. Record
   content hashes, decoder durations, duplicate recordings and incomplete pairs.
   Preserve recordings over the application's 600-second limit and list them as
   ineligible for the unmodified application benchmark. Do not silently truncate
   them or equate a crop with the full recording. If a separate crop experiment
   is needed, record its parent audio hash, explicit start/end offsets and crop
   hash; convert local result times back to parent-recording times before any
   comparison. A different released version still needs separate validation.
4. Honor the existing reserved `test pair` designation. Develop on nonreserved
   cases, track shared recordings across cases, and keep reserved references out
   of model inputs, retrieval and threshold tuning. Freeze changes before the
   reserved comparison. A case's reference text is not instrument evidence.
5. Resolve recording-version warnings before timing scores. Distinguish direct
   recording reuse from interpolation: publishing reference timings do not
   establish a positive master-recording match.
6. Produce baseline and candidate predictions from the same audio, model weights,
   resource limits and settings. Retain all attempted cases, abstentions,
   timeouts and missing-file errors in the denominator. Record runtime and peak
   memory as well as candidate boundaries; do not only report successful pairs.
7. Compare actual temporal overlap and boundaries, not only total covered
   seconds. Two intervals of equal length can be at entirely different points in
   a song. The existing `scripts/evaluate.py` reports duration error, so that
   figure alone must not be called timestamp accuracy. Where annotations are
   complete, report union intersection-over-union, time precision/recall and
   boundary error; where they are partial, report overlap with the annotated
   regions and leave unannotated regions unassessed.
8. Preserve separately the predicted intervals, human reference intervals and
   reviewer edits. A small controlled regression improvement cannot replace the
   existing evaluation score or establish performance on an inaccessible
   corpus. Report exactly which cases and pipeline stages were run.

Deployment and changes to external services are separate from this local
evaluation. Keep the existing application and its interaction flow available
while candidate changes are assessed.
