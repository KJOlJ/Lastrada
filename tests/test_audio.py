import numpy as np
import pytest
from lastrada.audio.io import prepare, decode, wav_bytes
from lastrada.audio.synthetic import demo_pair
from lastrada.measurement.pfnmf import measure
from lastrada.alignment.intervals import coverage, merge_ranges
from lastrada.alignment.local import refine_candidate
from lastrada.schemas.models import Interval


def test_union_coverage_not_double_counted():
    intervals = [
        Interval(new_start=s, new_end=e, source="synthetic") for s, e in [(1, 4), (3, 6), (8, 9)]
    ]
    assert coverage(intervals, 10) == (6, 60)
    with pytest.raises(ValueError, match="exceeds"):
        coverage(intervals, 5)


def test_invalid_interval_rejected():
    with pytest.raises(ValueError):
        merge_ranges([(2, 1)])


def test_normalization_and_decode():
    audio, _, _ = demo_pair()
    encoded = wav_bytes(audio)
    result = decode(encoded, 16000)
    assert result.sample_rate == 16000
    assert abs(result.duration - 4) < 0.01
    assert np.isfinite(result.samples).all()
    assert np.max(abs(result.samples)) <= 1.01


def test_synthetic_pfnmf_recovers_coverage():
    original, new, ranges = demo_pair()
    result = measure(original, new)
    expected = sum(e - s for s, e in ranges) / new.duration * 100
    assert abs(result.coverage_percentage - expected) < 5
    assert len(result.intervals) == 2
    assert abs(result.intervals[0].new_start - 2.0) < 0.1
    assert any("not verified" in warning for warning in result.warnings)


def test_silence_measurement():
    audio = prepare(np.zeros(8000), 8000)
    result = measure(audio, audio)
    assert result.coverage_percentage == 0
    assert result.intervals == []


def test_invalid_audio():
    with pytest.raises(ValueError):
        prepare(np.array([np.nan] * 8000), 8000)
    with pytest.raises(ValueError):
        decode(b"")


def test_waveform_refinement_covers_the_contiguous_verified_copy():
    original, new, _ = demo_pair()
    coarse = Interval(
        new_start=1.8,
        new_end=6.0,
        original_start=0.0,
        original_end=4.0,
        source="candidate",
        status="candidate",
    )
    refined = refine_candidate(original, new, coarse)
    assert refined.source == "direct_waveform_local_alignment"
    assert abs(refined.new_start - 2) < 0.02
    # The generated source is copied for four seconds, then an unmatched gap.
    assert refined.new_end - refined.new_start == pytest.approx(4)
    assert refined.status == "candidate"


def test_stereo_downmix_and_mp3_decode(tmp_path):
    import shutil
    import subprocess
    import soundfile as sf

    if not shutil.which("ffmpeg"):
        pytest.skip("FFmpeg is optional in core CI; PCM/FLAC decoding tested separately")
    original, _, _ = demo_pair()
    wave = tmp_path / "generated.wav"
    compressed = tmp_path / "generated.mp3"
    sf.write(
        wave, np.column_stack([original.samples, original.samples * 0.5]), original.sample_rate
    )
    subprocess.run(
        ["ffmpeg", "-v", "error", "-nostdin", "-i", str(wave), str(compressed)], check=True
    )
    result = decode(compressed.read_bytes())
    assert result.samples.ndim == 1
    assert result.sample_rate == 16000
    assert abs(result.duration - 4) < 0.1
