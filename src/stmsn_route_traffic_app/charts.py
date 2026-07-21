import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

PERIOD_COLORS = {"A": "#1f77b4", "B": "#ff7f0e"}
DIRECTION_DASH = {"NB": "solid", "SB": "dash"}


def _bin_slots(df: pd.DataFrame, slot_col: str, metric_col: str, bin_minutes: int) -> pd.DataFrame:
    """Bin slot_local strings into bin_minutes buckets and compute median + IQR."""
    # Parse "HH:MM" → total minutes
    df = df.copy()
    df["_minutes"] = df[slot_col].str.split(":").apply(lambda x: int(x[0]) * 60 + int(x[1]))
    df["_bin"] = (df["_minutes"] // bin_minutes) * bin_minutes

    result = (
        df.groupby(["period", "direction", "_bin"])[metric_col]
        .agg(median="median", q25=lambda x: np.percentile(x, 25), q75=lambda x: np.percentile(x, 75))
        .reset_index()
    )
    # Convert bin back to "HH:MM"
    result["slot_binned"] = result["_bin"].apply(lambda m: f"{m // 60:02d}:{m % 60:02d}")
    return result


def profile_chart(
    slot_df: pd.DataFrame,
    window: str,
    directions: list[str],
    metric_col: str,
    metric_label: str,
    bin_minutes: int = 10,
) -> go.Figure:
    """
    Plotly line chart: x=slot_local, y=median metric, IQR band, lines per period.
    One trace group per direction (distinguished by line dash).
    """
    sub = slot_df[slot_df["time_window"] == window]
    if sub.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{window} peak — no data", height=300)
        return fig

    binned = _bin_slots(sub, "slot_local", metric_col, bin_minutes)
    fig = go.Figure()

    for direction in directions:
        for period in ["A", "B"]:
            grp = binned[(binned["direction"] == direction) & (binned["period"] == period)].sort_values("slot_binned")
            if grp.empty:
                continue
            color = PERIOD_COLORS[period]
            dash = DIRECTION_DASH.get(direction, "solid")
            name = f"Period {period} {direction}"

            # IQR band (upper first, then lower fill)
            fig.add_trace(go.Scatter(
                x=grp["slot_binned"],
                y=grp["q75"],
                mode="lines",
                line=dict(width=0),
                showlegend=False,
                hoverinfo="skip",
            ))
            fig.add_trace(go.Scatter(
                x=grp["slot_binned"],
                y=grp["q25"],
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor=f"rgba({_hex_to_rgb(color)},0.15)",
                showlegend=False,
                hoverinfo="skip",
            ))
            # Median line
            fig.add_trace(go.Scatter(
                x=grp["slot_binned"],
                y=grp["median"],
                mode="lines",
                name=name,
                line=dict(color=color, dash=dash, width=2),
                hovertemplate=f"<b>{name}</b><br>Slot: %{{x}}<br>{metric_label}: %{{y:.0f}}<extra></extra>",
            ))

    fig.add_hline(y=0, line_dash="dot", line_color="gray", line_width=1)
    fig.update_layout(
        title=f"{window} peak — {metric_label}",
        xaxis_title="Time slot",
        yaxis_title=metric_label,
        height=350,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=40),
    )
    return fig


def coverage_heatmap(df: pd.DataFrame, period: str) -> go.Figure:
    """Day-of-week × time_window heatmap of mean coverage_pct for one period."""
    sub = df[df["period"] == period]
    if sub.empty:
        fig = go.Figure()
        fig.update_layout(title=f"Period {period} — no data", height=200)
        return fig

    dow_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    pivot = (
        sub.groupby(["day_of_week_name", "time_window"])["coverage_pct"]
        .mean()
        .unstack(fill_value=0)
    )
    # Reorder rows to day-of-week order
    pivot = pivot.reindex([d for d in dow_order if d in pivot.index])
    windows = list(pivot.columns)

    fig = go.Figure(go.Heatmap(
        z=pivot.values * 100,
        x=windows,
        y=pivot.index.tolist(),
        colorscale=[[0, "#d73027"], [0.6, "#fee08b"], [1, "#1a9850"]],
        zmin=0,
        zmax=100,
        text=(pivot.values * 100).round(0).astype(int),
        texttemplate="%{text}%",
        showscale=False,
        hovertemplate="Day: %{y}<br>Window: %{x}<br>Coverage: %{z:.0f}%<extra></extra>",
    ))
    fig.update_layout(
        title=f"Period {period} coverage",
        height=220,
        margin=dict(t=40, b=20, l=10, r=10),
        xaxis=dict(side="top"),
    )
    return fig


DIRECTION_COLORS = {"NB": "#1f77b4", "SB": "#ff7f0e"}


def daily_profile_chart(
    all_df: pd.DataFrame,
    selected_date,
    window: str,
    direction: str,
    hist_df: pd.DataFrame | None = None,
) -> go.Figure:
    """
    x=slot_local, y=duration_seconds for one window+direction.
    Solid line = selected day. Dotted grey lines = median/p25/p75 across prior same-weekday days.
    hist_df, if provided, replaces all_df as the reference pool for percentile lines.
    """
    sub = all_df[(all_df["time_window"] == window) & (all_df["direction"] == direction)].copy()
    if sub.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{window} {direction} — no data", height=300)
        return fig

    selected_date_str = str(selected_date)
    dow = pd.Timestamp(selected_date).strftime("%A")

    day_df = sub[sub["request_date_local"] == selected_date_str].sort_values("slot_local")

    ref_source = hist_df if hist_df is not None else all_df
    sub_ref = ref_source[(ref_source["time_window"] == window) & (ref_source["direction"] == direction)]
    ref_df = sub_ref[(sub_ref["day_of_week_name"] == dow) & (sub_ref["request_date_local"] != selected_date_str)]

    ref_stats = (
        ref_df.groupby("slot_local")["duration_seconds"]
        .quantile([0.25, 0.5, 0.75])
        .unstack()
        .rename(columns={0.25: "p25", 0.5: "median", 0.75: "p75"})
        .reset_index()
        .sort_values("slot_local")
    )
    n_days = ref_df.groupby("slot_local")["request_date_local"].nunique().rename("n_days")
    ref_stats = ref_stats.join(n_days, on="slot_local")

    color = DIRECTION_COLORS.get(direction, "#888888")
    fig = go.Figure()

    if not ref_stats.empty:
        fig.add_trace(go.Scatter(
            x=ref_stats["slot_local"], y=ref_stats["p75"],
            customdata=ref_stats[["n_days"]],
            mode="lines", line=dict(color="gray", dash="dot", width=1),
            name="p75 (hist)", hovertemplate="p75: %{y:.0f}s (n=%{customdata[0]})<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=ref_stats["slot_local"], y=ref_stats["median"],
            customdata=ref_stats[["n_days"]],
            mode="lines", line=dict(color="gray", dash="dash", width=1.5),
            name="median (hist)", hovertemplate="Median: %{y:.0f}s (n=%{customdata[0]})<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=ref_stats["slot_local"], y=ref_stats["p25"],
            customdata=ref_stats[["n_days"]],
            mode="lines", line=dict(color="gray", dash="dot", width=1),
            name="p25 (hist)", hovertemplate="p25: %{y:.0f}s (n=%{customdata[0]})<extra></extra>",
        ))

    if not day_df.empty:
        fig.add_trace(go.Scatter(
            x=day_df["slot_local"], y=day_df["duration_seconds"],
            mode="lines+markers", line=dict(color=color, width=2),
            name=f"{direction} today",
            hovertemplate="Slot: %{x}<br>Duration: %{y:.0f}s<extra></extra>",
        ))

    fig.update_layout(
        title=f"{window} — {direction}",
        xaxis_title="Time slot",
        yaxis_title="Duration (s)",
        height=300,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=40),
    )
    return fig


def _hex_to_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r},{g},{b}"
