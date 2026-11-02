#!/usr/bin/env python3
"""Install and launch the existing local UI. No cloud services or model downloads."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
REQUIRED = ('lastrada', 'streamlit', 'numpy', 'scipy', 'sklearn', 'pandas',
            'soundfile', 'pydantic', 'plotly', 'openpyxl', 'threadpoolctl')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check only; install/start nothing')
    parser.add_argument('--setup', action='store_true', help='Refresh local app dependencies')
    parser.add_argument('--port', type=int, default=8501)
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise SystemExit('Install Python 3.12, then run this launcher with that Python.')
    if not 1024 <= args.port <= 65535:
        parser.error('Choose a port between 1024 and 65535')
    python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    if not python.is_file():
        if args.check:
            raise SystemExit('Local environment missing. Run this launcher without --check to create it.')
        subprocess.run([sys.executable, '-m', 'venv', str(ROOT / '.venv')], check=True)
    probe = 'import importlib.util; import sys; sys.exit(0 if all(importlib.util.find_spec(x) for x in ' + repr(REQUIRED) + ') else 1)'
    ready = subprocess.run([str(python), '-c', probe], cwd=ROOT).returncode == 0
    if args.check and not ready:
        raise SystemExit('Local app dependencies missing. Run without --check to install them.')
    if not args.check and (not ready or args.setup):
        print('Installing local app dependencies from package repositories; no cloud resources are created.', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-e', str(ROOT) + '[ui]'], check=True)
    print('Local UI: Streamlit on this computer; no Firebase or Community Cloud required.', flush=True)
    print('FFmpeg: ' + ('available' if shutil.which('ffmpeg') else 'not found; use WAV/FLAC if MP3 decoding fails.'), flush=True)
    checkpoint = Path(os.environ.get('LASTRADA_SAMPLEID_CHECKPOINT', ROOT / 'checkpoints/sampleid-best.ckpt'))
    if checkpoint.is_file():
        print('Checkpoint file found. Full Sony matching still needs the optional runtime and a valid model; inspect analysis warnings.', flush=True)
    else:
        print('Sony checkpoint not found at the configured/default path. Expect fallback analysis unless another supported model location is configured.', flush=True)
    print('PF-NMF fallback does not establish original-track timestamps or confirm a sample. Demucs is optional and runs only on request.', flush=True)
    if args.check:
        print('Local dependency check passed; pretrained model inference was not tested.')
        return
    print(f'Open http://127.0.0.1:{args.port} on THIS computer. Keep this window open; Ctrl+C stops the app.', flush=True)
    try:
        subprocess.run([str(python), '-m', 'streamlit', 'run', str(ROOT / 'app.py'),
                        '--server.address', '127.0.0.1', '--server.port', str(args.port),
                        '--browser.gatherUsageStats', 'false'], cwd=ROOT, check=True)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f'Local setup/start failed (exit {exc.returncode}). Keep the error above for troubleshooting.') from None
