import numpy as np
from lastrada.audio.io import prepare
from lastrada.audio.synthetic import demo_pair
from lastrada.reporting.comparison import spectral_view, comparison_figure
from lastrada.schemas.models import Interval


def test_spectral_display_is_bounded_and_silent_audio_is_dark():
    audio = prepare(np.zeros(8000 * 20), 8000)
    times, frequencies, db = spectral_view(audio)
    assert len(times) <= 600
    assert db.shape == (len(frequencies), len(times))
    assert np.isfinite(db).all()
    assert np.all(db == -80)


def test_hover_uses_source_evidence_without_inventing_original_times():
    original, new, _ = demo_pair()
    views = spectral_view(original), spectral_view(new)
    intervals = [
        Interval(new_start=2, new_end=3, source="pfnmf"),
        Interval(
            new_start=5,
            new_end=6,
            original_start=1,
            original_end=2,
            source="expert_review",
            status="expert_verified",
        ),
    ]
    fig = comparison_figure(*views, intervals)
    markers = [trace for trace in fig.data if trace.type == "scatter"]
    assert len(markers) == 3  # Only the located interval gets an original-track marker.
    assert "Not located" in markers[0].hovertemplate
    assert "Suggested moment" in markers[0].hovertemplate
    assert "Original: 0:01.00–0:02.00" in markers[1].hovertemplate
    assert "Confirmed by reviewer" in markers[1].hovertemplate
    assert markers[2].x[0] == 1.5
    assert len(fig.layout.shapes) == 3


def test_hover_explains_ambiguous_ending_without_calling_it_a_confidence_bound():
    original, new, _ = demo_pair()
    interval = Interval(
        new_start=2, new_end=3.5, original_start=1, original_end=2.5,
        source="direct_waveform_local_alignment",
        end_review={"new_through": 4, "original_through": 3},
    )
    fig = comparison_figure(spectral_view(original), spectral_view(new), [interval])
    marker = next(trace for trace in fig.data if trace.type == "scatter")
    assert "Ending unclear" in marker.hovertemplate
    assert "0:04.00 in your track" in marker.hovertemplate
    assert "0:03.00 in the original" in marker.hovertemplate
    assert "Audio may continue beyond these points" in marker.hovertemplate
    assert "Listen through" not in marker.hovertemplate
