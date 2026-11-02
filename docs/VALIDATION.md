# v0 validation evidence

Validated in a Python 3.12 Linux cloud environment on CPU with FFmpeg available.

- `pytest -q`: 97 tests passed, including numerical coverage, synthetic PF-NMF, compressed decoding, strict input/leakage boundaries, rights isolation, candidate grouping, review invariants, evaluation abstentions and a Streamlit interaction workflow with Next/Back navigation, saved edits and approval preservation.
- `ruff check .` and `git diff --check`: passed.
- Synthetic end-to-end baseline: known coverage 66.67%, estimated spectral activation 67.07%, absolute error 0.40 percentage points. This single generated signal pair is not a real-music benchmark.
- `scripts/check_sampleid.py`: authoritative checksum-verified Sony weights, CPU inference, embedding shape 1×2048 and self-match cosine approximately 0.99999988. This is integration evidence, not historical accuracy.
- `scripts/install.sh` followed by `scripts/install_sampleid.sh`: repeat setup completed; existing weights verified rather than downloaded again.
- Streamlit launched and served its health endpoint and HTML. Its interaction test executed synthetic intake, analysis, correction persistence and unresolved-approval rejection.

Historical ingestion/audit completed locally. Reserved-case evaluation listed unavailable/unconfirmed cases explicitly; no real placement accuracy or paragraph quality result is claimed. Detailed audit/evaluation outputs remain ignored and private. Actual client audio was not supplied.

The app can process uploaded audio and generate reviewable drafts. Publishing localization, musical characterization, section labels and final judgments require human evidence. Snapshot publication and restoration in a fresh task have not been independently validated.

The seven-screen interface was checked in headless Chromium: primary-button labels rendered navy on pale blue in both themes, only the active screen was visible, timing suggestions carried into musical details, and custom draft text survived forward/back navigation.

Landing/restart and quality gates were checked in Streamlit tests and Chromium. Accepting PF-NMF suggested times preserves their exact start/end values; editing is unlocked only on disagreement. A clean restart clears analysis, preliminary results and uploads while preserving the theme. No master/publishing inference accuracy is claimed.

Filename-credit parsing covers Unicode artists, explicit “by” names, conventional artist/title separators, ambiguous filenames and preserving user corrections. Browser checks uploaded generated WAVs with both filename conventions and submitted edited credits.

Mixed-use regression: a creator can confirm a recording sample, explicitly choose no replayed/re-sung music, and finish without publishing timestamps or musical details. Browser checks confirm irrelevant fields disappear while recording evidence remains required. No-use exports exclude stale positive details.

For creator-selected “throughout” placement, generated narrative and HTML/text Nature of Use exports summarize placement instead of enumerating occurrences. Loop descriptions and detailed JSON evidence remain intact; other placements retain their timestamps.

Spectral comparison tests verify bounded display data, silence rendering and evidence-aware hover labels: unlocated source passages are explicit, and original-track highlights require supplied source timestamps. Display aggregation does not modify PF-NMF intervals.

Chromium rendered both spectral panels after synthetic analysis and displayed the suggested-moment tooltip on hover, including the explicit unlocated-source message.

Performance regression checks count analysis, encoding, spectrum and figure calls across review edits and navigation. Default intake performs PF-NMF once; two audio encodes and two spectral transforms are reused. Non-listening screens emit no audio or Plotly chart. Chromium verified that review interactions retain the existing chart DOM, navigation updates the active screen, and musical edits survive backtracking. Preview reuse preserves measurement evidence and isolates requested rights without mutating the original preview. These are local checks, not hosted latency measurements.

Both-use regression: confirming recording reuse and replayed music permits the description step even when automatic publishing times are unavailable. Unfinished timing checks are shown on Place the sample and block final review/document generation. Publishing times stay independent of master measurements; empty tables have no accept-times option.

The both-use fix was rebased onto the existing Sony/DTW integration and all 97 tests passed. UI regression tests explicitly disable optional Sony inference to keep listening/form checks deterministic; the production matching default is preserved.

Lightweight-flow checks: 97 tests pass, including explicit-only stem calls,
cache-hit review preservation, one-of-50 candidate budgeting, eight-second
probe bounds, single-thread worker environment, disk separation reuse,
section-map overlap classification, stale-default clearing and retaining human
edits. No timestamp rule invents a verse/chorus/bridge label. In Chromium,
recognized generated-WAV filenames skipped the credit screen and reached timing
review in 1.6 seconds in one local run with Sony disabled. The no-replay answer
hid that path; method/repetition prefills and the section-map UI rendered.
This is not a real-music benchmark or Streamlit-hosted performance result.
