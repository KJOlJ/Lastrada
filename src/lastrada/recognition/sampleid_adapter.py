"""Optional local CPU SampleID inference and conservative candidate grouping.

Sony embeddings are used for relative retrieval, not as calibrated sampling
probabilities. Candidate regions therefore require a coherent time-progressing
sequence of top-ranked window matches before they enter DTW or human review.
"""

from collections import defaultdict
from dataclasses import dataclass
import hashlib
import importlib
import importlib.util
from pathlib import Path
import sys

import numpy as np
from scipy.signal import resample_poly

from lastrada.schemas.models import Interval


class SampleIDUnavailable(RuntimeError):
    pass


@dataclass
class Embeddings:
    values: np.ndarray
    starts: np.ndarray
    ends: np.ndarray
    hop_seconds: float = 1.0


def chunks(audio, seconds=5.0, hop=1.0):
    if seconds <= 0 or hop <= 0 or hop > seconds:
        raise ValueError("Chunk/hop must be positive and hop must not exceed chunk length")
    divisor = np.gcd(audio.sample_rate, 16000)
    samples = resample_poly(audio.samples, 16000 // divisor, audio.sample_rate // divisor)
    length, step = int(seconds * 16000), int(hop * 16000)
    starts = list(range(0, max(1, len(samples) - length + step), step))
    pieces, valid = [], []
    for start in starts:
        segment = samples[start : start + length]
        if np.sqrt(np.mean(segment**2)) < 1e-6:
            continue
        pieces.append(np.pad(segment, (0, length - len(segment))).astype(np.float32))
        valid.append(start / 16000)
    return pieces, np.asarray(valid), np.minimum(np.asarray(valid) + seconds, audio.duration)


def _rank_points(similarity, top_k, minimum_similarity):
    """Keep only each derivative window's strongest relative source matches."""
    points = []
    order = np.argsort(-similarity, axis=1)
    for new_index, ranked_source in enumerate(order[:, :top_k]):
        row = similarity[new_index]
        median = float(np.median(row))
        mad = float(1.4826 * np.median(np.abs(row - median)) + 1e-9)
        for rank_zero, source_index in enumerate(ranked_source):
            score = float(row[source_index])
            if minimum_similarity is not None and score < minimum_similarity:
                continue
            points.append(
                {
                    "new_index": int(new_index),
                    "source_index": int(source_index),
                    "rank": int(rank_zero + 1),
                    "similarity": score,
                    "relative_z": float((score - median) / mad),
                }
            )
    return points


def _sequence_candidates(
    similarity,
    original,
    new,
    *,
    top_k,
    minimum_similarity,
    minimum_support,
    slope_min=0.5,
    slope_max=2.0,
    slope_step=0.05,
    line_tolerance_windows=1.0,
    max_new_gap=2,
):
    """Find time-progressing paths without compressing skipped silent windows."""
    points = _rank_points(similarity, top_k, minimum_similarity)
    candidates = []
    bucket_width = max(1e-6, 2.0 * line_tolerance_windows * original.hop_seconds)

    for slope in np.arange(slope_min, slope_max + 1e-9, slope_step):
        buckets = defaultdict(list)
        for point in points:
            intercept = (
                original.starts[point["source_index"]] - slope * new.starts[point["new_index"]]
            )
            bucket = int(round(intercept / bucket_width))
            buckets[bucket].append(point)

        for bucket_points in buckets.values():
            bucket_points.sort(key=lambda item: (item["new_index"], item["rank"]))
            runs = []
            current = []
            last_new = None
            for point in bucket_points:
                new_time = float(new.starts[point["new_index"]])
                if last_new is None or new_time - last_new <= max_new_gap * new.hop_seconds:
                    current.append(point)
                else:
                    if current:
                        runs.append(current)
                    current = [point]
                last_new = new_time
            if current:
                runs.append(current)

            for run in runs:
                best_by_new = {}
                for point in run:
                    old = best_by_new.get(point["new_index"])
                    if old is None or point["rank"] < old["rank"]:
                        best_by_new[point["new_index"]] = point
                run = sorted(best_by_new.values(), key=lambda item: item["new_index"])
                if len(run) < minimum_support:
                    continue

                new_times = np.asarray(
                    [new.starts[point["new_index"]] for point in run], dtype=float
                )
                source_times = np.asarray(
                    [original.starts[point["source_index"]] for point in run], dtype=float
                )
                fitted_slope, fitted_intercept = np.polyfit(new_times, source_times, 1)
                predicted = fitted_slope * new_times + fitted_intercept
                rmse = (
                    float(np.sqrt(np.mean((source_times - predicted) ** 2))) / original.hop_seconds
                )
                if not slope_min <= fitted_slope <= slope_max:
                    continue
                if rmse > line_tolerance_windows:
                    continue

                mean_rank = float(np.mean([point["rank"] for point in run]))
                mean_similarity = float(
                    np.mean([point["similarity"] for point in run])
                )
                mean_relative_z = float(
                    np.mean([point["relative_z"] for point in run])
                )
                rank_quality = (top_k + 1.0 - mean_rank) / top_k
                straightness = 1.0 / (1.0 + rmse)
                contrast = 1.0 + 0.1 * max(0.0, min(mean_relative_z, 3.0))
                sequence_score = len(run) * rank_quality * straightness * contrast

                first_new = int(min(point["new_index"] for point in run))
                last_new = int(max(point["new_index"] for point in run))
                first_source = int(min(point["source_index"] for point in run))
                last_source = int(max(point["source_index"] for point in run))
                candidates.append(
                    {
                        "sequence_score": sequence_score,
                        "mean_similarity": mean_similarity,
                        "new_start": float(new.starts[first_new]),
                        "new_end": float(new.ends[last_new]),
                        "source_start": float(original.starts[first_source]),
                        "source_end": float(original.ends[last_source]),
                        "new_indices": {
                            int(point["new_index"]) for point in run
                        },
                        "source_range": (first_source, last_source),
                    }
                )
    return candidates


def _deduplicate(candidates, maximum_candidates):
    """Collapse paths found repeatedly at neighboring scanned slopes."""
    candidates.sort(key=lambda item: item["sequence_score"], reverse=True)
    kept = []
    for candidate in candidates:
        duplicate = False
        for old in kept:
            new_overlap = len(candidate["new_indices"] & old["new_indices"])
            new_denom = max(
                1,
                min(len(candidate["new_indices"]), len(old["new_indices"])),
            )
            source_start, source_end = candidate["source_range"]
            old_start, old_end = old["source_range"]
            source_overlap = max(
                0,
                min(source_end, old_end) - max(source_start, old_start) + 1,
            )
            source_denom = max(
                1,
                min(source_end - source_start + 1, old_end - old_start + 1),
            )
            if new_overlap / new_denom >= 0.6 and source_overlap / source_denom >= 0.5:
                duplicate = True
                break
        if not duplicate:
            kept.append(candidate)
        if len(kept) >= maximum_candidates:
            break
    return kept


def group_candidates(
    original,
    new,
    threshold=0.8,
    top_k=3,
    minimum_support=3,
    maximum_candidates=50,
):
    """Return coherent SampleID regions using rank plus temporal consistency.

    ``threshold`` is retained only as a weak floor for backward compatibility.
    It is not interpreted as a probability or the primary decision rule.
    """
    if not -1 <= threshold <= 1 or top_k < 1 or minimum_support < 2:
        raise ValueError("Invalid SampleID candidate configuration")
    for embeddings in (original, new):
        if not np.isfinite(embeddings.hop_seconds) or embeddings.hop_seconds <= 0:
            raise ValueError("Embedding window hop must be finite and positive")
        if (
            len(embeddings.values) != len(embeddings.starts)
            or len(embeddings.starts) != len(embeddings.ends)
            or not np.isfinite(embeddings.starts).all()
            or not np.isfinite(embeddings.ends).all()
            or np.any(np.diff(embeddings.starts) <= 0)
            or np.any(embeddings.ends <= embeddings.starts)
        ):
            raise ValueError("Embedding timestamps must be finite, ordered, positive intervals")
    if not len(original.values) or not len(new.values):
        return []

    source_values = original.values / np.maximum(
        np.linalg.norm(original.values, axis=1, keepdims=True), 1e-12
    )
    new_values = new.values / np.maximum(
        np.linalg.norm(new.values, axis=1, keepdims=True), 1e-12
    )
    similarity = new_values @ source_values.T

    raw = _sequence_candidates(
        similarity,
        original,
        new,
        top_k=top_k,
        minimum_similarity=threshold,
        minimum_support=minimum_support,
    )
    candidates = _deduplicate(raw, maximum_candidates)
    return [
        Interval(
            new_start=item["new_start"],
            new_end=item["new_end"],
            original_start=item["source_start"],
            original_end=item["source_end"],
            source="sampleid_rank_sequence",
            status="candidate",
            similarity=float(np.clip(item["mean_similarity"], -1, 1)),
        )
        for item in candidates
    ]


def _prepare_sampleid_model_imports():
    """Expose Sony's private checkpoint modules as top-level ``src``.

    Pip may clone an editable VCS dependency into this project's ``src/sampleid``
    directory. Because Lastrada itself uses a ``src`` layout, ``import sampleid``
    can then resolve to a namespace package whose ``__file__`` is ``None``. Find
    the real nested Sony package in either layout, put its directory first on
    ``sys.path``, and clear any unrelated top-level ``src`` namespace before
    Hydra instantiates checkpoint classes such as
    ``src.networks.resnet_ibn.ResnetIBN``.
    """
    import sampleid as imported_sampleid

    package_root = None
    SampleID = getattr(imported_sampleid, "SampleID", None)
    module_file = getattr(imported_sampleid, "__file__", None)
    if module_file:
        package_root = Path(module_file).resolve().parent
    else:
        for namespace_entry in getattr(imported_sampleid, "__path__", []):
            namespace_root = Path(namespace_entry).resolve()
            nested_package = namespace_root / "sampleid"
            if (nested_package / "__init__.py").is_file():
                actual_package = importlib.import_module("sampleid.sampleid")
                SampleID = getattr(actual_package, "SampleID", None)
                package_root = nested_package
                break

    if package_root is None or SampleID is None:
        raise SampleIDUnavailable(
            "Sony SampleID's installed source package could not be located. "
            "Reinstall the pinned upstream repository in editable/source form."
        )

    sony_src = package_root / "src"
    if not sony_src.is_dir():
        raise SampleIDUnavailable(
            "Sony SampleID source modules are missing. Install the pinned "
            "upstream repository in editable/source form."
        )

    root_text = str(package_root)
    while root_text in sys.path:
        sys.path.remove(root_text)
    sys.path.insert(0, root_text)

    loaded_src = sys.modules.get("src")
    loaded_paths = {
        Path(value).resolve()
        for value in getattr(loaded_src, "__path__", [])
    }
    if loaded_src is not None and sony_src.resolve() not in loaded_paths:
        for module_name in list(sys.modules):
            if module_name == "src" or module_name.startswith("src."):
                sys.modules.pop(module_name, None)

    importlib.invalidate_caches()
    try:
        importlib.import_module("src.networks.resnet_ibn")
    except Exception as exc:
        raise SampleIDUnavailable(
            "Sony checkpoint model modules could not be imported from the "
            "installed SampleID source."
        ) from exc

    return SampleID


class SampleIDAdapter:
    def __init__(self, checkpoint, cache_dir="cache/sampleid", batch_size=4):
        if not checkpoint or not Path(checkpoint).is_file():
            raise SampleIDUnavailable(
                "SampleID checkpoint is not installed. PF-NMF remains available."
            )
        if not importlib.util.find_spec("torch") or not importlib.util.find_spec("sampleid"):
            raise SampleIDUnavailable("Install CPU PyTorch and the pinned Sony SampleID package.")
        if batch_size < 1:
            raise ValueError("Batch size must be positive")
        self.checkpoint = Path(checkpoint)
        self.cache_dir = Path(cache_dir)
        self.batch_size = batch_size
        digest = hashlib.sha256()
        with self.checkpoint.open("rb") as file:
            for block in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(block)
        self.model_hash = digest.hexdigest()
        self._model = None

    def _load(self):
        if self._model is None:
            import torch

            SampleID = _prepare_sampleid_model_imports()
            torch.set_num_threads(2)
            try:
                self._model = SampleID.load_checkpoint(
                    str(self.checkpoint), device=torch.device("cpu")
                )
            except SampleIDUnavailable:
                raise
            except Exception as exc:
                raise SampleIDUnavailable(
                    f"SampleID checkpoint could not load ({type(exc).__name__})."
                ) from exc
        return self._model

    def embed(self, audio, seconds=5.0, hop=1.0):
        key = hashlib.sha256(
            audio.samples.tobytes()
            + f"{audio.sample_rate}:{seconds}:{hop}:{self.model_hash}:v2".encode()
        ).hexdigest()
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        cached = self.cache_dir / f"{key}.npz"
        if cached.is_file():
            with np.load(cached, allow_pickle=False) as data:
                return Embeddings(data["values"], data["starts"], data["ends"], hop_seconds=hop)
        pieces, starts, ends = chunks(audio, seconds, hop)
        if not pieces:
            return Embeddings(np.empty((0, 0)), starts, ends, hop_seconds=hop)
        import torch

        model = self._load()
        result = []
        try:
            with torch.inference_mode():
                for start in range(0, len(pieces), self.batch_size):
                    batch = torch.from_numpy(np.stack(pieces[start : start + self.batch_size]))
                    result.append(model(batch, audio=True).cpu().numpy().reshape(len(batch), -1))
        except Exception as exc:
            raise SampleIDUnavailable(f"SampleID inference failed ({type(exc).__name__}).") from exc
        values = np.concatenate(result)
        if not np.isfinite(values).all():
            raise SampleIDUnavailable("SampleID produced non-finite embeddings")
        temporary = cached.with_suffix(".tmp")
        with temporary.open("wb") as file:
            np.savez_compressed(file, values=values, starts=starts, ends=ends)
        temporary.replace(cached)
        return Embeddings(values, starts, ends, hop_seconds=hop)

    def match(self, original, new, threshold=0.8, seconds=5.0, hop=1.0):
        return group_candidates(
            self.embed(original, seconds, hop),
            self.embed(new, seconds, hop),
            threshold=threshold,
        )
