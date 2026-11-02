"""Bounded per-occurrence stem checks; suggestions never replace human review."""

import hashlib
import json
import os
from pathlib import Path
from time import monotonic

from lastrada.alignment.stems import compare_candidate_stems
from lastrada.pipeline import _stem_evidence_records, short_stem_candidate
from lastrada.reporting.suggestions import suggested_intervals
from lastrada.schemas.models import InstrumentOccurrence
from lastrada.separation.demucs import DemucsSeparator, StemSeparationUnavailable

LABELS = {
    "guitar": "Guitar",
    "piano": "Piano",
    "bass": "Bass",
    "drums": "Drums",
    "vocals": "Vocals",
    "other": "Other sounds (unidentified)",
}
TERMINAL = {"checked", "no_source", "too_short"}
MIN_PROBE_SECONDS = 2.0


def occurrence_id(interval):
    values = [
        getattr(interval, k) for k in ("new_start", "new_end", "original_start", "original_end")
    ]
    return hashlib.sha256(json.dumps(values).encode()).hexdigest()[:24]


def occurrence_rows(result, model_name=None):
    previous = {r.occurrence_id: r for r in result.instrument_occurrences}
    rows = []
    for index, interval in enumerate(suggested_intervals(result, "master"), 1):
        key = occurrence_id(interval)
        row = (
            previous[key].model_copy(deep=True)
            if key in previous
            else InstrumentOccurrence(
                occurrence_id=key, candidate_number=index, interval=interval.model_copy(deep=True)
            )
        )
        row.candidate_number = index
        if model_name and row.model_name != model_name:
            row = InstrumentOccurrence(
                occurrence_id=key,
                candidate_number=index,
                interval=interval.model_copy(deep=True),
                model_name=model_name,
            )
        if interval.original_start is None:
            row.status, row.reason = (
                "no_source",
                "Original-track times are needed for an instrument comparison.",
            )
        elif (
            min(
                interval.new_end - interval.new_start,
                interval.original_end - interval.original_start,
            )
            < MIN_PROBE_SECONDS
        ):
            row.status, row.reason = (
                "too_short",
                "This moment is too short for a reliable instrument comparison (under two seconds).",
            )
        rows.append(row)
    return rows


def instrument_check_complete(result, model_name=None):
    rows = occurrence_rows(result, model_name)
    return bool(rows) and all(r.status in TERMINAL for r in rows)


def instrument_progress(result):
    rows = occurrence_rows(result)
    return {
        "finished": sum(r.status in TERMINAL for r in rows),
        "total": len(rows),
        "checked": sum(r.status == "checked" for r in rows),
    }


def instrument_prefill(result, model_name=None):
    labels = []
    for row in occurrence_rows(result, model_name):
        if row.status == "checked":
            for label in row.suggested_instruments:
                if label not in labels:
                    labels.append(label)
    if not labels:
        return {}
    return {"element": ", ".join(labels), "method": "Sampled the original recording"}


def run_occurrence_instruments(
    result,
    original,
    new,
    settings,
    *,
    separator=None,
    on_progress=None,
    budget_seconds=600,
    max_new_checks=50,
):
    """Check bounded probes in every eligible row, saving partial work for continuation.

    At most 10 minutes / 50 new comparisons per request. Cached completed rows are
    reused even after worker restarts; Demucs additionally caches exact crops.
    """
    updated = result.model_copy(deep=True)
    updated.instrument_occurrences = occurrence_rows(updated, settings.stem_model_name)
    began = monotonic()
    count = 0

    def persist():
        updated.methods["instruments"] = f"demucs_{settings.stem_model_name}_per_occurrence_v1"
        updated.timings_seconds["instrument_checks"] = monotonic() - began
        if on_progress:
            on_progress(updated)

    persist()
    for row in updated.instrument_occurrences:
        if row.status in TERMINAL:
            continue
        remaining = budget_seconds - (monotonic() - began)
        if count >= max_new_checks or remaining < 20:
            break
        if separator is None:
            try:
                separator = DemucsSeparator(
                    model_name=settings.stem_model_name,
                    device=settings.stem_device,
                    cache_dir=Path(os.getenv("LASTRADA_CACHE_DIR", "cache")) / "demucs",
                    segment_seconds=4,
                    timeout_seconds=settings.stem_timeout_seconds,
                )
            except (StemSeparationUnavailable, OSError, RuntimeError, ValueError) as exc:
                row.status, row.reason = "failed", str(exc)
                persist()
                break
        separator.timeout_seconds = max(
            1, min(settings.stem_timeout_seconds, int((remaining - 10) / 2))
        )
        row.probe = short_stem_candidate([row.interval], min(8.0, settings.stem_probe_seconds))
        row.evidence, row.suggested_instruments = [], []
        try:
            comparison = compare_candidate_stems(
                original,
                new,
                row.probe,
                separator,
                separation_padding=1,
                dtw_search_padding=1,
                max_pitch_shift_semitones=2,
                minimum_duration_ratio=0.5,
                maximum_duration_ratio=2,
                minimum_duration=1,
                include_cross_other=False,
            )
            row.evidence = _stem_evidence_records([comparison])
            for evidence in row.evidence:
                evidence.candidate_number = row.candidate_number
                if (
                    evidence.dtw_result == "accepted"
                    and evidence.source_stem == evidence.new_song_stem
                    and evidence.source_stem in LABELS
                ):
                    row.suggested_instruments.append(LABELS[evidence.source_stem])
            row.status = "checked"
            row.reason = (
                "Possible supporting matches in the checked portion; confirm by listening."
                if row.suggested_instruments
                else "No reliable instrument match in the checked portion."
            )
        except (StemSeparationUnavailable, OSError, RuntimeError, ValueError) as exc:
            row.status, row.reason = "failed", str(exc)
            persist()
            break  # Model/download failures should not repeat across every row.
        count += 1
        persist()
    updated.stem_evidence = [e for row in updated.instrument_occurrences for e in row.evidence]
    updated.methods["stems"] = (
        f"demucs_{settings.stem_model_name}_per_occurrence; short probes; creator confirmation required"
    )
    persist()
    return updated


def record_initial_comparisons(result, candidates, updated, comparisons, settings):
    """Attach the fast profile's initial comparisons without repeating separation.

    Main-flow DTW retains its exploratory acceptance rules. Instrument prefills
    additionally reject short probes and extreme duration ratios. A cross-label
    match can refine a candidate without establishing a named instrument.
    """
    eligible = [
        (index, before, updated[index])
        for index, before in enumerate(candidates[: settings.stem_max_candidates])
        if before.original_start is not None and before.original_end is not None
    ]
    rows = []
    for (index, probe, interval), comparison in zip(eligible, comparisons, strict=True):
        evidence = _stem_evidence_records([comparison])
        for item in evidence:
            item.candidate_number = index + 1
        too_short = (
            min(probe.new_end - probe.new_start, probe.original_end - probe.original_start)
            < MIN_PROBE_SECONDS
        )
        labels = list(
            dict.fromkeys(
                LABELS[item.source_stem]
                for item in evidence
                if not too_short
                and item.dtw_result == "accepted"
                and item.source_stem == item.new_song_stem
                and item.source_stem in LABELS
                and item.duration_ratio is not None
                and 0.5 <= item.duration_ratio <= 2
            )
        )
        rows.append(
            InstrumentOccurrence(
                occurrence_id=occurrence_id(interval),
                model_name=settings.stem_model_name,
                candidate_number=index + 1,
                interval=interval.model_copy(deep=True),
                probe=probe.model_copy(deep=True),
                status="too_short" if too_short else "checked",
                evidence=evidence,
                suggested_instruments=labels,
                reason="Initial fast-profile comparison; confirm estimates by listening.",
            )
        )
    result.instrument_occurrences = rows
