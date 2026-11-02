"""Optional Demucs source separation for candidate-region experiments.

The separator processes only padded candidate regions, never whole recordings by
default. Demucs stems are estimates with possible bleed and artifacts; they are
supporting evidence, not recovered studio multitracks.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import soundfile as sf

from lastrada.audio.io import Audio


class StemSeparationUnavailable(RuntimeError):
    pass


@dataclass
class SeparatedRegion:
    stems: dict[str, Audio]
    offset_seconds: float
    candidate_start_local: float
    candidate_end_local: float
    crop_duration: float
    model_name: str
    cache_path: Path


def demucs_available() -> bool:
    return importlib.util.find_spec("demucs") is not None


def _mono_finite(samples: np.ndarray) -> np.ndarray:
    y = np.asarray(samples, dtype=np.float32)
    if y.ndim == 2:
        y = y.mean(axis=1)
    if y.ndim != 1 or not len(y) or not np.isfinite(y).all():
        raise StemSeparationUnavailable("Demucs returned invalid audio")
    return y


def _audio_from_file(path: Path) -> Audio:
    samples, sample_rate = sf.read(path, dtype="float32", always_2d=True)
    y = _mono_finite(samples)
    return Audio(y, int(sample_rate), len(y) / float(sample_rate))


def _crop_audio(audio: Audio, start: float, end: float) -> Audio:
    left = max(0, int(round(start * audio.sample_rate)))
    right = min(len(audio.samples), int(round(end * audio.sample_rate)))
    if right <= left:
        raise StemSeparationUnavailable("Candidate crop is empty")
    samples = audio.samples[left:right].astype(np.float32, copy=True)
    return Audio(samples, audio.sample_rate, len(samples) / audio.sample_rate)


def _region_key(
    crop: Audio,
    *,
    start: float,
    end: float,
    model_name: str,
) -> str:
    digest = hashlib.sha256()
    digest.update(crop.samples.tobytes())
    digest.update(f"{crop.sample_rate}:{start:.6f}:{end:.6f}:{model_name}:v1".encode())
    return digest.hexdigest()


class DemucsSeparator:
    """Run Demucs through its CLI and cache separated candidate regions."""

    def __init__(
        self,
        *,
        model_name: str = "htdemucs",
        device: str = "cpu",
        cache_dir: str | Path = "cache/demucs",
        segment_seconds: int | float = 7,
        overlap: float = 0.10,
        timeout_seconds: int = 1800,
    ):
        if not demucs_available():
            raise StemSeparationUnavailable(
                "Demucs is not installed. Install the optional stems dependencies."
            )
        if device not in {"cpu", "cuda"}:
            raise ValueError("Demucs device must be 'cpu' or 'cuda'")
        if not 0 <= overlap < 1:
            raise ValueError("Demucs overlap must be between 0 and 1")
        if segment_seconds <= 0:
            raise ValueError("Demucs segment length must be positive")

        # Demucs' command-line parser requires --segment to be an integer.
        # Floor positive values so older callers that supplied 7.5 remain
        # compatible while staying below the transformer model's segment cap.
        normalized_segment = int(segment_seconds)
        if normalized_segment <= 0:
            raise ValueError("Demucs segment length must be at least one second")

        self.model_name = model_name
        self.device = device
        self.cache_dir = Path(cache_dir)
        self.segment_seconds = normalized_segment
        self.overlap = float(overlap)
        self.timeout_seconds = int(timeout_seconds)

    def separate_region(
        self,
        audio: Audio,
        candidate_start: float,
        candidate_end: float,
        *,
        padding_seconds: float = 4.0,
    ) -> SeparatedRegion:
        if candidate_end <= candidate_start:
            raise ValueError("Candidate end must be after candidate start")
        if padding_seconds < 0:
            raise ValueError("Stem-separation padding cannot be negative")

        crop_start = max(0.0, float(candidate_start) - padding_seconds)
        crop_end = min(audio.duration, float(candidate_end) + padding_seconds)
        crop = _crop_audio(audio, crop_start, crop_end)
        key = _region_key(
            crop,
            start=crop_start,
            end=crop_end,
            model_name=self.model_name,
        )
        cache_path = self.cache_dir / key
        manifest_path = cache_path / "manifest.json"

        if not manifest_path.is_file():
            self._run_and_cache(crop, cache_path, crop_start, crop_end)

        return self._load_cached_region(
            cache_path,
            candidate_start=float(candidate_start),
            candidate_end=float(candidate_end),
        )

    def _run_and_cache(
        self,
        crop: Audio,
        cache_path: Path,
        crop_start: float,
        crop_end: float,
    ) -> None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(dir=cache_path.parent) as folder:
            work = Path(folder)
            input_path = work / "candidate.wav"
            output_path = work / "separated"
            sf.write(input_path, crop.samples, crop.sample_rate, subtype="PCM_16")

            command = [
                sys.executable,
                "-m",
                "demucs",
                "-n",
                self.model_name,
                "-d",
                self.device,
                "--shifts",
                "0",
                "--overlap",
                str(self.overlap),
                "--segment",
                str(self.segment_seconds),
                "-o",
                str(output_path),
                str(input_path),
            ]
            environment = os.environ.copy()
            # Keep each CPU worker small even if the host sets larger BLAS pools.
            environment["OMP_NUM_THREADS"] = "1"
            environment["MKL_NUM_THREADS"] = "1"
            environment["OPENBLAS_NUM_THREADS"] = "1"

            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    env=environment,
                )
            except subprocess.TimeoutExpired as exc:
                raise StemSeparationUnavailable(
                    "Demucs timed out while separating the candidate region"
                ) from exc

            if result.returncode:
                details = (result.stderr or result.stdout or "")[-2000:]
                raise StemSeparationUnavailable(
                    f"Demucs failed with exit code {result.returncode}: {details}"
                )

            expected = output_path / self.model_name / input_path.stem
            stem_files = sorted(expected.glob("*.wav")) if expected.is_dir() else []
            if not stem_files:
                stem_files = sorted(output_path.rglob("*.wav"))
            if not stem_files:
                raise StemSeparationUnavailable("Demucs produced no stem files")

            staged = work / "cache"
            staged.mkdir()
            # Retain the exact crop as a full-mix baseline.
            sf.write(
                staged / "full_mix.wav",
                crop.samples,
                crop.sample_rate,
                subtype="PCM_16",
            )
            stem_names = ["full_mix"]

            for stem_file in stem_files:
                stem_name = stem_file.stem.lower()
                destination = staged / f"{stem_name}.wav"
                shutil.copy2(stem_file, destination)
                stem_names.append(stem_name)

            manifest = {
                "model_name": self.model_name,
                "device": self.device,
                "crop_start": crop_start,
                "crop_end": crop_end,
                "crop_duration": crop.duration,
                "stems": sorted(set(stem_names)),
            }
            (staged / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

            if cache_path.exists():
                shutil.rmtree(cache_path)
            shutil.move(str(staged), str(cache_path))

    def _load_cached_region(
        self,
        cache_path: Path,
        *,
        candidate_start: float,
        candidate_end: float,
    ) -> SeparatedRegion:
        manifest_path = cache_path / "manifest.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StemSeparationUnavailable("Demucs cache manifest is invalid") from exc

        stems = {}
        for stem_name in manifest.get("stems", []):
            stem_path = cache_path / f"{stem_name}.wav"
            if stem_path.is_file():
                stems[stem_name] = _audio_from_file(stem_path)

        if not stems:
            raise StemSeparationUnavailable("No readable stems found in Demucs cache")

        offset = float(manifest["crop_start"])
        return SeparatedRegion(
            stems=stems,
            offset_seconds=offset,
            candidate_start_local=max(0.0, candidate_start - offset),
            candidate_end_local=max(0.0, candidate_end - offset),
            crop_duration=float(manifest["crop_duration"]),
            model_name=str(manifest["model_name"]),
            cache_path=cache_path,
        )
