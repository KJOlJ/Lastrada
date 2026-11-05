import numpy as np
import pytest
from lastrada.audio.synthetic import demo_pair
from lastrada.recognition.sampleid_adapter import (
    Embeddings,
    chunks,
    group_candidates,
    SampleIDAdapter,
    SampleIDUnavailable,
)


def test_model_optional_without_checkpoint(tmp_path):
    with pytest.raises(SampleIDUnavailable, match="not installed"):
        SampleIDAdapter(tmp_path / "missing.ckpt")


def test_chunks_cpu_mono_16khz_and_short_padding():
    original, new, _ = demo_pair()
    pieces, starts, ends = chunks(original)
    assert len(pieces) == 1
    assert pieces[0].shape == (80000,)
    assert starts[0] == 0 and ends[0] == 4
    pieces, starts, ends = chunks(new)
    assert len(pieces) == 8
    assert ends[-1] == 12


def test_grouped_candidates_temporal_consistency():
    values = np.eye(3)
    original = Embeddings(values, np.array([0, 1, 2]), np.array([5, 6, 7]))
    new = Embeddings(values, np.array([10, 11, 12]), np.array([15, 16, 17]))
    result = group_candidates(original, new, 0.9)
    assert len(result) == 1
    assert result[0].new_start == 10 and result[0].new_end == 17
    assert result[0].original_start == 0 and result[0].original_end == 7
    assert result[0].status == "candidate"


def test_unrelated_embeddings_no_candidate():
    original = Embeddings(np.array([[1.0, 0.0]]), np.array([0]), np.array([5]))
    new = Embeddings(np.array([[0.0, 1.0]]), np.array([0]), np.array([5]))
    assert group_candidates(original, new, 0.9) == []


def test_silent_windows_cannot_join_separate_occurrences():
    # Silence is omitted by chunks(), so array positions are not clock times.
    starts = np.array([0, 1, 2, 30, 31, 32], dtype=float)
    values = np.eye(6)
    original = Embeddings(values, starts, starts + 5)
    new = Embeddings(values, starts + 10, starts + 15)
    rows = group_candidates(original, new, threshold=0.9, top_k=1)
    assert sorted((r.new_start, r.new_end) for r in rows) == [(10, 17), (40, 47)]


def test_skipped_source_windows_use_source_clock_for_speed_guard():
    original = Embeddings(
        np.eye(6), np.array([0, 1, 2, 30, 31, 32]), np.array([5, 6, 7, 35, 36, 37])
    )
    new = Embeddings(np.eye(6), np.arange(10, 16), np.arange(15, 21))
    rows = group_candidates(original, new, threshold=0.9, top_k=1)
    assert rows
    assert all(r.original_end - r.original_start <= 7 for r in rows)


def test_isolated_matches_are_not_a_supported_continuous_sequence():
    original = Embeddings(np.eye(3), np.arange(3), np.arange(5, 8))
    starts = np.array([10, 40, 70])
    new = Embeddings(np.eye(3), starts, starts + 5)
    assert group_candidates(original, new, threshold=0.9, top_k=1) == []


@pytest.mark.parametrize("hop", [0.25, 0.5, 2.0])
def test_clock_grouping_preserves_configured_window_hop(hop):
    starts = np.array([0, 1, 2, 30, 31, 32], dtype=float) * hop
    original = Embeddings(np.eye(6), starts, starts + 5, hop_seconds=hop)
    new = Embeddings(np.eye(6), starts + 10, starts + 15, hop_seconds=hop)
    rows = group_candidates(original, new, threshold=0.9, top_k=1)
    assert sorted((r.new_start, r.new_end) for r in rows) == [
        (10, 15 + 2 * hop),
        (10 + 30 * hop, 15 + 32 * hop),
    ]


@pytest.mark.parametrize(
    "starts,ends,hop",
    [
        ([1, 1, 2], [6, 6, 7], 1),
        ([0, 1, np.nan], [5, 6, 7], 1),
        ([0, 1, 2], [5, 6, 1], 1),
        ([0, 1, 2], [5, 6, 7], 0),
    ],
)
def test_invalid_embedding_clocks_are_rejected(starts, ends, hop):
    embeddings = Embeddings(np.eye(3), np.array(starts), np.array(ends), hop_seconds=hop)
    with pytest.raises(ValueError, match="Embedding"):
        group_candidates(embeddings, embeddings)


def test_existing_embedding_cache_uses_requested_hop_without_loading_model(tmp_path):
    import hashlib
    from lastrada.audio.io import Audio

    audio = Audio(np.ones(16000, dtype=np.float32), 16000, 1.0)
    adapter = SampleIDAdapter.__new__(SampleIDAdapter)
    adapter.cache_dir, adapter.model_hash = tmp_path, "generated-model"
    hop = 0.25
    key = hashlib.sha256(
        audio.samples.tobytes() + f"16000:5.0:{hop}:generated-model:v2".encode()
    ).hexdigest()
    np.savez(tmp_path / f"{key}.npz", values=np.eye(3), starts=[0, 0.25, 0.5], ends=[1, 1, 1])
    cached = adapter.embed(audio, hop=hop)
    assert cached.hop_seconds == hop
    assert cached.starts.tolist() == [0, 0.25, 0.5]
