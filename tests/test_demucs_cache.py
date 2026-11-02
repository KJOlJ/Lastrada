from types import SimpleNamespace
from pathlib import Path
import numpy as np
import soundfile as sf
from lastrada.audio.io import prepare
from lastrada.separation.demucs import DemucsSeparator


def test_separation_cache_reuses_outputs_and_limits_worker_threads(monkeypatch, tmp_path):
    monkeypatch.setattr("lastrada.separation.demucs.demucs_available", lambda: True)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        folder = Path(command[command.index("-o") + 1]) / "htdemucs" / "candidate"
        folder.mkdir(parents=True)
        for name in ("bass", "drums", "vocals", "other"):
            sf.write(folder / f"{name}.wav", np.zeros(16000), 16000)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("lastrada.separation.demucs.subprocess.run", fake_run)
    separator = DemucsSeparator(cache_dir=tmp_path, segment_seconds=4, timeout_seconds=180)
    audio = prepare(np.sin(np.arange(16000) / 10), 16000)
    first = separator.separate_region(audio, 0, 1, padding_seconds=0)
    second = separator.separate_region(audio, 0, 1, padding_seconds=0)
    assert first.cache_path == second.cache_path
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[command.index("-n") + 1] == "htdemucs"
    assert command[command.index("--segment") + 1] == "4"
    assert kwargs["timeout"] == 180
    assert kwargs["env"]["OMP_NUM_THREADS"] == "1"
    assert kwargs["env"]["MKL_NUM_THREADS"] == "1"
    assert set(second.stems) == {"full_mix", "bass", "drums", "vocals", "other"}
