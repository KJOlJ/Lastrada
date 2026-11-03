"""Estimated stem activity, kept separate from evidence of sample reuse."""

import numpy as np

from lastrada.schemas.models import InstrumentPresence

LABELS = {
    "guitar": "Guitar",
    "piano": "Piano",
    "bass": "Bass",
    "drums": "Drums",
    "vocals": "Vocals",
    "other": "Other sounds (unidentified)",
}


def describe_region(region, start, end):
    """Measure the sample itself when >=250 ms; otherwise label context only.

    Shares describe separated-stem energy, not instrument probabilities. Bleed,
    model errors and cancellation prevent interpreting these as a true mix split.
    Quiet/absent stems are excluded instead of assigning every model label.
    """
    if region is None:
        return []
    scope = "sample"
    left, right = (
        max(start, region.offset_seconds),
        min(end, region.offset_seconds + region.crop_duration),
    )
    if right - left < 0.25:
        left = region.offset_seconds + region.candidate_start_local
        right = region.offset_seconds + region.candidate_end_local
        scope = "context"

    def energy(audio):
        a = max(0, round((left - region.offset_seconds) * audio.sample_rate))
        b = min(len(audio.samples), round((right - region.offset_seconds) * audio.sample_rate))
        samples = np.asarray(audio.samples[a:b], dtype=np.float64)
        return float(np.mean(samples**2)) if len(samples) else 0.0

    energies = {s: energy(a) for s, a in region.stems.items() if s in LABELS}
    total = sum(energies.values())
    full = energy(region.stems["full_mix"]) if "full_mix" in region.stems else total
    if full < 1e-8 or total < 1e-8:
        return []
    return [
        InstrumentPresence(
            instrument=LABELS[s], energy_share=e / total, scope=scope, start=left, end=right
        )
        for s, e in sorted(energies.items(), key=lambda item: (-item[1], item[0]))
        if e / total >= 0.08 and e >= full * 0.0025
    ]


def context_probe(interval, original_duration, new_duration, maximum=8):
    """Use 4–8 seconds for separation; never rewrite the actual timestamp row."""
    probe = interval.model_copy(deep=True)
    for prefix, duration in (("original", original_duration), ("new", new_duration)):
        start, end = getattr(interval, prefix + "_start"), getattr(interval, prefix + "_end")
        width = min(duration, maximum, max(4.0, end - start))
        left = max(0.0, min(duration - width, (start + end - width) / 2))
        setattr(probe, prefix + "_start", left)
        setattr(probe, prefix + "_end", left + width)
    return probe
