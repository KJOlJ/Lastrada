# Instrument evidence v2

The Firebase interface separates three questions: what sounds are estimated in
an original passage, what sounds are estimated in its use in the new mix, and
whether a distinctive sequence aligns between them. Presence in both recordings
does not establish reuse. Six-stem labels remain estimates (bass, drums, vocals,
guitar, piano and unidentified other sounds); they cannot name every instrument.

## Short clips and repeated uses

Short timestamp rows are eligible for checks instead of being terminally skipped.
Separation uses up to eight seconds, expanding small intervals toward four
seconds where the recording permits. The original timestamp rows are unchanged.
For clips at least 250 ms long, stem energy is measured within the actual clip
(or the checked subsection of a long interval). Smaller clips receive a clearly
marked surrounding-context estimate. Every estimate carries its actual start/end.
The UI shows both recordings' estimates, including when no alignment is accepted.

Presence excludes stems below 8% of total estimated stem energy, stems below
0.25% of full-mix energy, and near-silent crops. Energy shares are internal
measurements, not instrument confidence or true mix proportions. Separator bleed
and classification errors remain possible; listen to confirm.

Identical source intervals within a case/model/evidence version share one stored
source description. The new mix's description and alignment decisions remain
independent at every occurrence. Overlapping but different source intervals are
not forced to have the same description. Relationship summaries say how many
checked moments actually support each comparison. Rejected checks do not inflate
that count, and a legacy label without a stored comparison cannot invent evidence.

If a probe extends beyond the timestamp interval, its alignment evidence is
marked `scope=context` and the row `context_only=true`. It cannot prefill a claim
that the instrument was sampled in that interval. Supported same-label sample
comparisons can still prefill descriptions, without overwriting creator edits.
Neither source presence nor a context alignment fills in reuse method or role.

## Timing safeguards

DTW remains a candidate refiner, not a sampling detector. It now uses centered
chroma, slope-limited steps (1:1, 1:2, 2:1), and default duration bounds 0.5–2×.
An alignment must have changing pitch information, mean cosine cost at most 0.30,
and improve on a reversed-source control by at least 0.04. Source chroma temporal
variance must be at least 0.002. These are engineering abstention rules checked
with generated controls, not thresholds fitted to the reserved evaluation set or
calibrated probabilities. They can reject true uses, including stationary chords,
percussion, chopped/reordered samples and major time transformations.

Rejected refinements preserve the original coarse search interval. A decrease in
short rows, or a larger coarse interval containing an annotated start, must not
be presented as improved boundary accuracy. The existing sample retrieval model
and candidate limits remain unchanged.

## Saved cases, limits and verification

`InstrumentOccurrence.evidence_version=2` distinguishes current checks. Old
results remain readable but are marked pending for recheck; they cannot silently
supply current suggestions. The operation preserves saved timings and human
review, saves partial progress, and reuses cached separated audio. Existing
bounds remain: 50 checks / 600 seconds per operation and the existing deployment
CPU, memory, scaling, permissions and quotas. More clips being eligible can mean
more batches within those limits.

Deploy API, worker and frontend together for the new schema. Start a new case to
rerun main timing analysis; a per-moment instrument recheck does not replace saved
timestamp suggestions. No update is automatically deployed by pushing
`local/stem-fast`.

Regression checks cover copied/transposed/stretched generated phrases, silence,
noise, steady tones, reversed phrases, collapsed DTW paths, short context and
sample estimates, quiet bleed, old-cache migration, repeated-source consistency,
independent reuse decisions and browser review through document export. These
checks do not establish commercial-recording accuracy. The reserved benchmark
must retain its original criterion and denominator, report false-positive
controls separately, and use the same verified recording versions.
