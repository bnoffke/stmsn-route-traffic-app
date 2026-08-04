import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import timedelta

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


def _zero_based_top(*series) -> float:
    """Upper y-limit for a zero-anchored axis: 10% headroom above the largest value.

    Keeps the axis crossing at zero so a modest change in travel time reads as a
    modest change rather than filling the plot. Falls back to 60s when there's
    nothing to plot.
    """
    values = [
        s.max() for s in series
        if s is not None and len(s) and pd.notna(s.max())
    ]
    return max(values) * 1.1 if values else 60.0


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
        xaxis=dict(title="Time slot", fixedrange=True),
        yaxis=dict(
            title="Duration (s)",
            fixedrange=True,
            rangemode="tozero",
            range=[0, _zero_based_top(day_df["duration_seconds"], ref_stats.get("p75"))],
        ),
        height=300,
        dragmode=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=40),
    )
    return fig


WEEKDAY_ORDER = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def weekly_profile_chart(
    all_df: pd.DataFrame,
    week_start,
    week_end,
    window: str,
    direction: str,
    hist_df: pd.DataFrame | None = None,
) -> go.Figure:
    """
    x=day_of_week (Mon–Fri), y=duration_seconds for one window+direction.
    Solid line = current week's per-day median. Dotted grey lines = p25/median/p75
    of historical daily medians by weekday (excluding current week).
    """
    week_start_str = str(week_start)
    week_end_str = str(week_end)

    sub = all_df[(all_df["time_window"] == window) & (all_df["direction"] == direction)].copy()
    if sub.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{window} {direction} — no data", height=300)
        return fig

    # Current-week line: per-day median, reindexed to Mon–Fri order
    week_rows = sub[
        (sub["request_date_local"] >= week_start_str) &
        (sub["request_date_local"] <= week_end_str)
    ]
    week_medians = (
        week_rows.groupby("day_of_week_name")["duration_seconds"]
        .median()
        .reindex(WEEKDAY_ORDER)
    )

    # Historical band: exclude current week, compute per-date daily median,
    # then per weekday take p25/50/75 across those daily medians.
    ref_source = hist_df if hist_df is not None else all_df
    sub_ref = ref_source[
        (ref_source["time_window"] == window) &
        (ref_source["direction"] == direction) &
        (
            (ref_source["request_date_local"] < week_start_str) |
            (ref_source["request_date_local"] > week_end_str)
        )
    ]

    ref_stats = pd.DataFrame()
    if not sub_ref.empty:
        daily_medians = (
            sub_ref.groupby(["request_date_local", "day_of_week_name"])["duration_seconds"]
            .median()
            .reset_index()
        )
        ref_stats = (
            daily_medians.groupby("day_of_week_name")["duration_seconds"]
            .agg(
                p25=lambda x: np.percentile(x, 25),
                median="median",
                p75=lambda x: np.percentile(x, 75),
                n_days="count",
            )
            .reindex(WEEKDAY_ORDER)
            .reset_index()
        )

    color = DIRECTION_COLORS.get(direction, "#888888")
    fig = go.Figure()

    if not ref_stats.empty:
        valid = ref_stats.dropna(subset=["p75"])
        fig.add_trace(go.Scatter(
            x=valid["day_of_week_name"], y=valid["p75"],
            customdata=valid[["n_days"]],
            mode="lines", line=dict(color="gray", dash="dot", width=1),
            name="p75 (hist)", hovertemplate="p75: %{y:.0f}s (n=%{customdata[0]})<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=valid["day_of_week_name"], y=valid["median"],
            customdata=valid[["n_days"]],
            mode="lines", line=dict(color="gray", dash="dash", width=1.5),
            name="median (hist)", hovertemplate="Median: %{y:.0f}s (n=%{customdata[0]})<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=valid["day_of_week_name"], y=valid["p25"],
            customdata=valid[["n_days"]],
            mode="lines", line=dict(color="gray", dash="dot", width=1),
            name="p25 (hist)", hovertemplate="p25: %{y:.0f}s (n=%{customdata[0]})<extra></extra>",
        ))

    week_plot = week_medians.dropna()
    if not week_plot.empty:
        fig.add_trace(go.Scatter(
            x=week_plot.index, y=week_plot.values,
            mode="lines+markers", line=dict(color=color, width=2),
            name=f"{direction} this week",
            hovertemplate="Day: %{x}<br>Duration: %{y:.0f}s<extra></extra>",
        ))

    fig.update_layout(
        title=f"{window} — {direction}",
        xaxis=dict(
            title="Day of week",
            categoryorder="array",
            categoryarray=WEEKDAY_ORDER,
            fixedrange=True,
        ),
        yaxis=dict(
            title="Duration (s)",
            fixedrange=True,
            rangemode="tozero",
            range=[0, _zero_based_top(week_plot, ref_stats.get("p75"))],
        ),
        height=300,
        dragmode=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=40),
    )
    return fig


def _hex_to_rgb(hex_color: str) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"{r},{g},{b}"


def trend_chart(
    df: pd.DataFrame,
    granularity: str,
    window: str,
    direction: str,
    metric_col: str = "duration_seconds",
    change_dates: list | None = None,
) -> go.Figure:
    """
    Long trendline chart for Weekly View tab.
    granularity: "Week" | "Day" | "Intraday"
    df is pre-filtered to date range + holiday preference.
    """
    sub = df[(df["time_window"] == window) & (df["direction"] == direction)].copy()
    if sub.empty:
        fig = go.Figure()
        fig.update_layout(title=f"{window} — {direction} — no data", height=300)
        return fig

    color = DIRECTION_COLORS.get(direction, "#888888")
    fig = go.Figure()
    rangebreaks = [dict(bounds=["sat", "mon"])]

    if granularity == "Intraday":
        sub["_x"] = pd.to_datetime(
            sub["request_date_local"].astype(str) + " " + sub["slot_local"]
        )
        sub = sub.sort_values("_x")

        # Derive hour bounds from actual slot data to avoid hardcoding AM/PM hours
        slot_hours = pd.to_datetime(sub["slot_local"], format="%H:%M").dt.hour
        min_hour = int(slot_hours.min())
        max_hour = int(slot_hours.max())
        # rangebreak hides from max_hour+1 back around to min_hour (overnight gap)
        if max_hour + 1 < 24:
            rangebreaks.append(dict(bounds=[max_hour + 1, min_hour], pattern="hour"))

        fig.add_trace(go.Scatter(
            x=sub["_x"], y=sub[metric_col],
            mode="lines", line=dict(color=color, width=1),
            name=f"{direction}",
            hovertemplate="Date: %{x}<br>Duration: %{y:.0f}s<extra></extra>",
        ))

        y_top = _zero_based_top(sub[metric_col])

    else:
        # Week or Day aggregation
        if granularity == "Week":
            sub["_date"] = pd.to_datetime(sub["request_date_local"])
            sub["_x"] = sub["_date"] - pd.to_timedelta(sub["_date"].dt.weekday, unit="D")
            agg = (
                sub.groupby("_x")[metric_col]
                .agg(
                    p25=lambda x: np.percentile(x, 25),
                    median="median",
                    p75=lambda x: np.percentile(x, 75),
                    n="count",
                )
                .reset_index()
            )
            n_days_per_week = (
                sub.groupby("_x")["request_date_local"].nunique().rename("n_days")
            )
            agg = agg.join(n_days_per_week, on="_x")
            x_title = "Week of (Monday)"
            partial_threshold = 5  # full week = 5 days
            last_is_partial = agg["n_days"].iloc[-1] < partial_threshold if not agg.empty else False
        else:  # Day
            sub["_x"] = pd.to_datetime(sub["request_date_local"])
            agg = (
                sub.groupby("_x")[metric_col]
                .agg(
                    p25=lambda x: np.percentile(x, 25),
                    median="median",
                    p75=lambda x: np.percentile(x, 75),
                    n="count",
                )
                .reset_index()
            )
            agg["n_days"] = 1
            x_title = "Date"
            # Day is partial if the last date has fewer slots than the max seen
            max_n = agg["n"].max() if not agg.empty else 1
            last_is_partial = agg["n"].iloc[-1] < max_n if not agg.empty else False

        agg = agg.sort_values("_x")

        # p25 / p75 dotted grey lines
        fig.add_trace(go.Scatter(
            x=agg["_x"], y=agg["p75"],
            customdata=agg[["n"]],
            mode="lines", line=dict(color="gray", dash="dot", width=1),
            name="p75", hovertemplate="p75: %{y:.0f}s (n=%{customdata[0]})<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=agg["_x"], y=agg["p25"],
            customdata=agg[["n"]],
            mode="lines", line=dict(color="gray", dash="dot", width=1),
            name="p25", hovertemplate="p25: %{y:.0f}s (n=%{customdata[0]})<extra></extra>",
        ))

        # Median colored line — last point is open circle when partial
        cd_cols = ["n", "n_days"] if granularity == "Week" else ["n"]
        hover = "Median: %{y:.0f}s (n=%{customdata[0]}, days=%{customdata[1]})<extra></extra>" if granularity == "Week" else "Median: %{y:.0f}s (n=%{customdata[0]})<extra></extra>"
        n = len(agg)
        symbols = ["circle-open" if (last_is_partial and i == n - 1) else "circle" for i in range(n)]
        fig.add_trace(go.Scatter(
            x=agg["_x"], y=agg["median"],
            customdata=agg[cd_cols],
            mode="lines+markers",
            line=dict(color=color, width=2),
            marker=dict(color=color, symbol=symbols),
            name=f"{direction} median",
            hovertemplate=hover,
        ))

        y_top = _zero_based_top(agg["median"], agg["p75"])

    for cd in (change_dates or []):
        # Snap weekend dates to preceding Friday so the line isn't hidden by rangebreaks
        ts = pd.Timestamp(cd)
        if ts.weekday() > 4:
            ts = ts - timedelta(days=ts.weekday() - 4)
        fig.add_vline(x=ts, line=dict(color="gray", dash="dot", width=1.5))

    fig.update_layout(
        title=f"{window} — {direction}",
        xaxis=dict(
            title=x_title if granularity != "Intraday" else "Date / Time",
            type="date",
            fixedrange=True,
            rangebreaks=rangebreaks,
        ),
        yaxis=dict(
            title="Duration (s)",
            fixedrange=True,
            rangemode="tozero",
            range=[0, y_top],
        ),
        height=300,
        dragmode=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(t=60, b=40),
    )
    return fig
