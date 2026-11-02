# Strict $0 fallback: run on your own computer

Do not run `deploy/bootstrap.py --apply`: that deployment requires billing-enabled
services and is not approved under the user's free-plan-only restriction. Do not
link billing, upgrade Firebase, create service accounts or provision resources.

## What works today

The existing Streamlit interface can run locally, without Streamlit Community
Cloud, Firebase, Google sign-in, or paid APIs. This uses your own computer's CPU,
RAM and disk. It retains the upload, timestamp review and Nature of Use workflow.
This is a local Streamlit runtime, not the user's requested replacement interface.

The **new no-Streamlit web interface is not yet a standalone local app**. Its
production storage, upload sessions, queue and identity use Google services;
starting Uvicorn alone does not remove those dependencies. Browser tests mock
those transports and are not a usable local installation. A local replacement
needs filesystem storage, local upload handling, a bounded local job runner,
loopback-only access, and frontend authentication/configuration changes. That
work has not been implemented. Do not deploy a static shell as a working analyzer.

## Simple launcher

After downloading/cloning this branch and installing Python 3.12:

- Windows: double-click `Start-Lastrada.cmd`.
- macOS: open `Start-Lastrada.command`. If macOS will not execute the file, open
  Terminal in the checkout and run `bash Start-Lastrada.command`.
- Any platform: run `python3.12 run-local.py` (Windows: `py -3.12 run-local.py`).

The launcher creates the checkout's `.venv` if missing, installs the local UI
when its dependencies are missing, prints model/fallback warnings, and binds to
`127.0.0.1`. First setup needs internet for Python packages; it does not download
models or enable cloud services. Python itself must already be installed.
`--check` checks readiness without installing or launching; `--setup` refreshes
app dependencies. Close with Ctrl+C. Use `--port 8502` if 8501 is occupied.
The Windows wrapper has not been executed on Windows in this workspace.

## Existing local UI: Linux/macOS commands

Install Python 3.12 and FFmpeg using your operating system's normal tools. From
a checkout of `feat/firebase-web`:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[ui]'
.venv/bin/python -m streamlit run app.py --server.address 127.0.0.1
```

Open the localhost address printed by Streamlit. Keep it bound to `127.0.0.1`;
no public tunnel or hosting is needed. On Windows use `py -3.12 -m venv .venv`
and replace `.venv/bin/python` with `.venv\Scripts\python.exe`.

Start with the built-in synthetic demo. Without optional SampleID dependencies
and weights, recording analysis uses the experimental PF-NMF fallback; it does
not establish original-track timestamps or confirm a sample. Real Sony matching
requires the existing optional installer and a verified checkpoint:

```bash
bash scripts/install_sampleid.sh
.venv/bin/python scripts/check_sampleid.py
```

See `docs/SETUP.md` for installer details and the local checkpoint override. These
download software/model files; they do not purchase cloud resources. The user's
existing GCS checkpoint URL is not proof its hosting is on a free plan; this
fallback does not create or change that bucket. Prefer existing verified local
weights when available. Demucs remains optional and should only run on request.

## Limits and verification

There is no cloud subscription charge for executing on your own hardware, but
normal electricity, internet and disk usage remain. No benchmark has established
whether the user's machine has sufficient memory or acceptable runtime. CPU
inference can still be slow; moving off hosted services does not reduce its
computation. No pretrained inference was run as part of this fallback check.

The Codex environment verified Streamlit/Python/FFmpeg availability and the
existing synthetic pipeline smoke test. These checks do not establish successful
installation or performance on the user's computer. There is currently no
turnkey, fully local **no-Streamlit** interface in this branch.

Official plan constraints verified separately by the coordinating assistant:

- https://firebase.google.com/docs/projects/billing/firebase-pricing-plans
- https://firebase.google.com/docs/storage/faqs-storage-changes-announced-sept-2024
- https://firebase.google.com/pricing

Firebase Spark can serve static Hosting content and free-quota Google sign-in;
it cannot host this Python audio backend. Cloud Run is unavailable on Spark,
and Cloud Storage requires Blaze under the February 2026 requirement. Free
allowances on a billing-enabled plan do not satisfy the user's restriction.
