# Local Sony + DTW + stem-assisted workflow

Stem separation is a second-stage validation step in the normal seven-screen Lastrada website. It does not launch the old DTW Lab.

## Analysis order

1. Sony SampleID proposes paired original/new-track candidates.
2. Direct waveform alignment or guarded full-mix DTW refines each candidate.
3. When stem assistance is enabled, Demucs separates the padded candidate regions for every Sony candidate returned by the adapter, up to its current maximum of 50 candidates. It does not separate the full recordings.
4. Guarded DTW compares selected estimated stem pairs: matching labels plus guitar/piano ↔ `other` spillover checks.
5. The exploratory DTW duration-ratio range is 0.1× to 10×. This intentionally permits extreme speed changes, but it also materially increases false-positive risk.
6. A successful stem alignment may refine a still-coarse Sony interval. It does not replace an existing direct-waveform or full-mix DTW refinement.
7. Step 3 shows the stem evidence and the final paired timings inside the normal listening-review flow.

Demucs stems are model estimates with possible bleed and artifacts. A label such as `guitar → guitar` is supporting evidence, not a final musical-element conclusion. Every accepted row still requires listening review.

## Windows PowerShell

From a checkout of `feat/stem-assisted-main-flow`:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
powershell -ExecutionPolicy Bypass -File .\scripts\install_sampleid.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\install_stems.ps1
```

Place `sampleid-best.ckpt` at `checkpoints\sampleid-best.ckpt` or set its full path:

```powershell
$env:LASTRADA_SAMPLEID_CHECKPOINT = (Resolve-Path ".\checkpoints\sampleid-best.ckpt").Path
```

Enable exhaustive stem assistance:

```powershell
$env:LASTRADA_STEM_ENABLED = "1"
$env:LASTRADA_STEM_MODEL = "htdemucs_6s"
$env:LASTRADA_STEM_DEVICE = "cpu"
$env:LASTRADA_STEM_MAX_CANDIDATES = "50"
$env:LASTRADA_STEM_PADDING_SECONDS = "4.0"
$env:LASTRADA_STEM_CROSS_OTHER = "1"
```

Verify the effective settings:

```powershell
.\.venv\Scripts\python.exe -c "from lastrada.config import load_settings; s=load_settings(); print({'min_ratio': s.dtw_min_duration_ratio, 'max_ratio': s.dtw_max_duration_ratio, 'stem_candidates': s.stem_max_candidates})"
```

Expected:

```text
{'min_ratio': 0.1, 'max_ratio': 10.0, 'stem_candidates': 50}
```

Verify Sony, then launch the main website:

```powershell
.\.venv\Scripts\python.exe .\scripts\diagnose_sampleid.py
.\.venv\Scripts\python.exe -m streamlit run app.py
```

The first `htdemucs_6s` analysis downloads Demucs model weights. Evaluating every Sony candidate can be very slow on CPU and can create hundreds of stem-pair rows. Results are cached under `cache\demucs` for repeat runs.

## Expected Step 3 result

The stem-evidence table includes a `Candidate` column when more than one Sony candidate is evaluated. When stem-assisted DTW refines a coarse Sony interval, its timing source appears as, for example:

```text
stem-assisted DTW · guitar → guitar
```

The technical-details expander also includes a `stems` method summary and `stem_separation` processing time. If Demucs is unavailable or no paired Sony candidate exists, the Sony/full-mix result remains unchanged and the reason is recorded in the methods/warnings output.
