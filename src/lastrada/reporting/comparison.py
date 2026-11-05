"""Bounded spectral displays and evidence-aware hover labels."""

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from lastrada.audio.io import prepare
from lastrada.measurement.pfnmf import spectrogram
from lastrada.reporting.document import timestamp


def spectral_view(audio):
    audio = prepare(audio.samples, audio.sample_rate, 8000)
    magnitude = spectrogram(audio)
    # Keep long recordings responsive without changing analysis measurements.
    stride = max(1, int(np.ceil(magnitude.shape[1] / 600)))
    starts = np.arange(0, magnitude.shape[1], stride)
    magnitude = np.maximum.reduceat(magnitude, starts, axis=1)[::2]
    peak = max(float(magnitude.max()), 1e-12)
    db = np.clip(20 * np.log10(np.maximum(magnitude, 1e-12) / peak), -80, 0)
    if magnitude.max() <= 1e-12:
        db.fill(-80)
    return starts * 128 / 8000 + 256 / 8000, np.arange(0, 257, 2) * 8000 / 512, db


def comparison_figure(original_view, new_view, intervals, dark=True):
    fig = make_subplots(
        rows=2, cols=1, subplot_titles=("The original", "Your track"), vertical_spacing=0.18
    )
    for row, view in enumerate((original_view, new_view), 1):
        times, frequencies, db = view
        fig.add_trace(
            go.Heatmap(
                x=times,
                y=frequencies,
                z=db,
                coloraxis="coloraxis",
                hovertemplate="Time: %{x:.2f}s<br>Frequency: %{y:.0f} Hz<br>Level: %{z:.0f} dB relative to this track’s peak<extra></extra>",
            ),
            row=row,
            col=1,
        )
    for number, interval in enumerate(intervals, 1):
        new_range = f"{timestamp(interval.new_start)}–{timestamp(interval.new_end)}"
        source_range = (
            f"{timestamp(interval.original_start)}–{timestamp(interval.original_end)}"
            if interval.original_start is not None
            else "Not located — PF-NMF does not identify source times"
        )
        label = (
            "Confirmed by reviewer"
            if interval.status == "expert_verified"
            else "Suggested moment — check by listening"
        )
        if interval.end_review is not None:
            label += (
                "<br>Ending unclear: quiet or masked audio may continue. Listen through "
                f"{timestamp(interval.end_review.new_through)} in your track and "
                f"{timestamp(interval.end_review.original_through)} in the original."
            )
        hover = f"Moment {number}<br>Your track: {new_range}<br>Original: {source_range}<br>{label}<extra></extra>"
        for row, start, end in [
            (2, interval.new_start, interval.new_end),
            (1, interval.original_start, interval.original_end),
        ]:
            if start is None:
                continue
            fig.add_vrect(
                x0=start, x1=end, fillcolor="#73e6cf", opacity=0.18, line_width=0, row=row, col=1
            )
            fig.add_trace(
                go.Scatter(
                    x=[(start + end) / 2],
                    y=[3700],
                    mode="markers",
                    marker=dict(color="#b3fff0", size=9, symbol="diamond"),
                    hovertemplate=hover,
                    showlegend=False,
                ),
                row=row,
                col=1,
            )
    fig.update_layout(
        height=510,
        margin=dict(l=20, r=30, t=40, b=35),
        template="plotly_dark" if dark else "plotly_white",
        paper_bgcolor="#091426" if dark else "#f7f9fc",
        coloraxis=dict(
            colorscale="Magma", cmin=-80, cmax=0, colorbar=dict(title="dB", thickness=10)
        ),
    )
    fig.update_xaxes(title_text="Time (seconds)")
    fig.update_yaxes(title_text="Frequency (Hz)", range=[0, 4000])
    return fig
