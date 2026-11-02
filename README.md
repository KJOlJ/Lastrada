# Lastrada · Nature of Use assistant

Local Python/Streamlit v0 for analyzing a known original/new-recording pair and drafting documentation for expert review. This is a documentation assistant, not a licensing rate calculator or legal clearance decision.

## Run

Python 3.12+ and `uv`:

```bash
cd /workspace/Lastrada
bash scripts/install.sh
.venv/bin/python -m streamlit run app.py --server.address 0.0.0.0
```

Alternatively, create a virtual environment with `python -m venv .venv`, install `requirements.lock` with pip, then install this project using `pip install --no-deps -e .` inside that environment. FFmpeg is recommended for compressed formats; soundfile supports WAV/FLAC and many MP3 files. No paid APIs are required.

## Deploy on Streamlit Community Cloud

Use repository `tankr98/Lastrada`, branch `feat/lastrada-v0`, entrypoint `app.py`, and Python 3.12. Production dependencies and native audio packages are declared in `requirements.txt` and `packages.txt`. Set app sharing to **Only specific people can view this app** before client uploads. See [deployment instructions](docs/DEPLOYMENT.md).

## A seven-screen creator workflow

The landing page introduces **Your Music, Your Time.** with a centered Start button. **New Sample** is available on every screen and clears the case, uploads and edits while preserving the theme. The workspace opens in navy dark mode with a light-mode toggle, progress at the top and a compact collapsible sidebar. Each screen focuses on one task, with compact buttons and a subtle transition that respects reduced-motion preferences.

1. **Add your tracks:** upload the original and your new recording, then select **Find my sample**. Recognized titles/artists allow a direct jump to the analysis and timestamps.
2. **Track details:** title and artist prefill from recognizable filenames (`Title by Artist` or conventional `Artist - Title`), remain editable, and preserve creator corrections. This screen is needed only when credits are missing or you want to change them. **Check both types — recommended** is the default; you do not need rights terminology before starting.
3. **Listen & check:** play both tracks and accept or edit the suggested timestamps. Answer whether you separately replayed a melody or re-sang lyrics; answering no skips that table. If a reuse type does not apply, choose “I didn’t replay or re-sing anything” or “I didn’t use the original recording”; its timestamps and musical details are skipped. Two spectral views appear after analysis with zoom and hover markers. Tooltips show both track ranges when original positions are available; PF-NMF-only suggestions explicitly leave source positions unknown. Technical details are optional.
4. **Describe the sound:** review the suggested reuse method and repetition, then name the sound and its musical role.
5. **Place the sample:** review timestamp-based placement/section suggestions. An optional song-section map matches your named verse, chorus or bridge ranges to sample times for both paths.
6. **Review your draft:** generate and edit the Nature of Use text, add your name and save or mark it as reviewed.
7. **Your Nature of Use:** preview and download HTML or text. When placement is “throughout,” the document describes that placement without listing every occurrence; detailed times remain in the supporting JSON. HTML can be printed to PDF; supporting JSON is optional.

Estimated master-analysis times populate a read-only table. Accept them to carry their exact values into the review, or choose **No, let me edit** to unlock corrections; publishing never inherits them. Timing patterns prompt questions about recurring use, melody and short loops. Timestamp rules prefill editable method, repetition and placement/section suggestions without replacing creator edits. They do not confirm evidence or identify verse versus chorus from timing alone; see [timing rules](docs/TIMING_PREFILLS.md). Suggested times need a separate listening confirmation.

**Back** and **Next** preserve session inputs; the final Next saves the review draft. Marking a document as reviewed requires confirmed findings, checked details and a reviewer name. Confirming each applicable type of use unlocks the description step. Timestamp checks may be completed on Listen & check or Place the sample; missing or unconfirmed times block final review. Each Next button requires the relevant musical details. Document generation and the final screen require complete musical inputs, confirmed details, a description and the reviewer’s name. In-progress edits can be saved as a session draft. Recording reuse and compositional reuse stay separate.

Playback and analysis run in the hosting workspace. There is no external model API. Uploads and reviews are session-local, not a persistent case database. Downloaded documents contain case information and need approved private storage.

## Capability status

| Capability | v0 status |
|---|---|
| Audio validation, mono normalization, resampling, playback | Functional; 100 MB / 10 minute input limits |
| PF-NMF spectral activation and union coverage | Experimental, synthetic-validated baseline; not a detector |
| SampleID CPU chunk embeddings, caching, grouped candidates | CPU inference verified on generated audio; optional Sony package/checkpoint required; see setup guide |
| Publishing interpolation localization | Expert input required; not automatically implemented |
| Placement | Conservative proposals; section labels and final class need expert review |
| Element, lyrics, transformations, musical role | Unknown automatically; expert correction supported |
| Nature of Use drafting, separate reviewed versions, JSON/HTML export | Functional deterministic templates |
| Historical retrieval | Local optional spreadsheet; all reserved cases excluded |
| Real-case evaluation | Harness implemented; requires audio, confirmed labels and version checks |

Similarity and PF-NMF activation never create a verified sample claim. `unknown`, `not_verified`, `not_detected`, `candidate`, and `verified` remain separate. Lack of recording matches does not establish lack of compositional reuse.

## Validate

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
.venv/bin/python scripts/diagnose.py
.venv/bin/python scripts/synthetic_smoke.py
```

See [setup](docs/SETUP.md), [architecture and decisions](docs/TECHNICAL_DECISIONS.md), [project plan](docs/PROJECT_PLAN.md), [data dictionary](docs/DATA_DICTIONARY.md), [audit procedure](docs/DATA_AUDIT.md), [evaluation](docs/EVALUATION.md), and [open questions](docs/OPEN_QUESTIONS.md).

## Confidentiality

Client documents, historical workbooks, commercial recordings, checkpoints, caches and real analysis outputs are not repository assets. Keep them outside this public checkout or under ignored `data/private/`, `outputs/`, and `cache/`. Only synthetic fixtures belong in source control. `.gitignore` helps prevent accidents; inspect staged changes before publishing.

### Interaction performance

Review controls use a Streamlit fragment so ordinary entries do not rebuild playback or spectral charts. Audio bytes and spectral views are retained within the private session; charts refresh when their evidence or theme changes and render only on the listening screen. Downloads render on the final screen. Small input widgets stay mounted to preserve backtracking edits. Confirming credits reuses the preliminary analysis when the upload identities, demonstration mode and settings are unchanged; enabling optional matching runs its analysis separately. New Sample clears these session assets.

### Lighter optional instrument check

The main analysis never runs Demucs automatically. **Explore instruments** runs
only on request, after a paired source/new-track candidate exists. It selects
one strongest pair, caps each probe at eight seconds plus one-second margins,
and uses `htdemucs` (four stems), four-second processing segments and one CPU
thread per worker. A process-wide lock permits only one main analysis or instrument request at a
time. Complete probe results are reused in the session and separated audio is
cached on disk; a cache hit does not restore an older review. The extra probe
never replaces the complete main-analysis timestamps. Sony/full-mix DTW evidence
and final review requirements remain unchanged.
