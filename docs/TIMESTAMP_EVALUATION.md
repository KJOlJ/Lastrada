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
   existing expert evaluation score or establish performance on an inaccessible
   corpus. Report exactly which cases and pipeline stages were run.

Deployment and changes to external services are separate from this local
evaluation. Keep the existing application and its interaction flow available
while candidate changes are assessed.
