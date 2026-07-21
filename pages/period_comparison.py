import streamlit as st
import pandas as pd
from datetime import date, timedelta
from streamlit_folium import st_folium

from stmsn_route_traffic_app.data import load_routes, load_daily, load_slots, load_date_range
from stmsn_route_traffic_app.metrics import (
    METRICS,
    SLOT_METRICS,
    matched_cells,
    filter_to_matched,
    coverage_summary,
    grade,
    headline_deltas,
)
from stmsn_route_traffic_app.charts import profile_chart, coverage_heatmap
from stmsn_route_traffic_app.mapview import corridor_map

# ── Shared state ──────────────────────────────────────────────────────────────
routes_df = load_routes()
corridor = st.session_state.get("corridor", sorted(routes_df["corridor"].unique())[0])
corridor_routes = routes_df[routes_df["corridor"] == corridor]

# ── Sidebar controls ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Comparison settings")

    all_dirs = sorted(corridor_routes["direction"].unique())
    direction_choice = st.radio("Direction", ["Both"] + all_dirs, horizontal=True)

    data_start, data_end = load_date_range()
    days_to_monday = (7 - data_start.weekday()) % 7
    first_monday = data_start + timedelta(days=days_to_monday)
    total_weeks = (data_end - first_monday).days // 7
    half_weeks = max(total_weeks // 2, 1)
    split = first_monday + timedelta(weeks=half_weeks)
    default_a_start = first_monday
    default_a_end = split - timedelta(days=1)
    default_b_start = split
    default_b_end = first_monday + timedelta(weeks=total_weeks) - timedelta(days=1)

    st.subheader("Period A")
    period_a_start = st.date_input("Start A", value=default_a_start, key="a_start")
    period_a_end = st.date_input("End A", value=default_a_end, key="a_end")

    st.subheader("Period B")
    period_b_start = st.date_input("Start B", value=default_b_start, key="b_start")
    period_b_end = st.date_input("End B", value=default_b_end, key="b_end")

    window_map = {"AM peak": "AM", "PM peak": "PM", "Noon probe": "NOON"}
    selected_window_labels = st.multiselect(
        "Window(s)",
        list(window_map.keys()),
        default=["AM peak", "PM peak"],
    )
    selected_windows = tuple(window_map[w] for w in selected_window_labels)

    include_weekends = st.toggle("Include weekends", value=False)
    if include_weekends:
        st.caption(":orange[Weekend data enabled — outputs are descriptive only, not inferential.]")

    metric_label = st.radio("Metric", list(METRICS.keys()))
    metric_col = METRICS[metric_label]
    slot_metric_col = SLOT_METRICS[metric_label]

    bin_30 = st.toggle("30-min slot bins", value=False)
    bin_minutes = 30 if bin_30 else 10

# ── Resolve selected route names ─────────────────────────────────────────────
if direction_choice == "Both":
    selected_dirs = all_dirs
else:
    selected_dirs = [direction_choice]

selected_routes = tuple(
    corridor_routes[corridor_routes["direction"].isin(selected_dirs)]["route_name"].tolist()
)

period_a = (str(period_a_start), str(period_a_end))
period_b = (str(period_b_start), str(period_b_end))

if not selected_windows:
    st.warning("Select at least one window in the sidebar.")
    st.stop()

# ── Load data ─────────────────────────────────────────────────────────────────
daily_df = load_daily(selected_routes, period_a, period_b, selected_windows, include_weekends)
slot_df = load_slots(selected_routes, period_a, period_b, selected_windows, include_weekends)

cells = matched_cells(daily_df)

# ── 1. Map + sample adequacy (top row) ───────────────────────────────────────
st.subheader(f"Corridor: {corridor}")

if daily_df.empty:
    st.warning("No data found for the selected corridor and date ranges.")
    st.stop()

n_matched = len(cells)
matched_days_a = daily_df[daily_df["period"] == "A"]["request_date_local"].nunique()
matched_days_b = daily_df[daily_df["period"] == "B"]["request_date_local"].nunique()

col_map, col_a, col_b = st.columns([1, 2, 2])

with col_map:
    m = corridor_map(routes_df, list(selected_routes))
    st_folium(m, height=320, use_container_width=True, returned_objects=[])

for col, period, label in [
    (col_a, "A", f"Period A  ({period_a[0]} → {period_a[1]})"),
    (col_b, "B", f"Period B  ({period_b[0]} → {period_b[1]})"),
]:
    with col:
        st.markdown(f"**{label}**")
        cov = coverage_summary(daily_df, period)
        if cov.empty:
            st.warning("No data in this period.")
            continue
        for _, row in cov.iterrows():
            g = grade(row["coverage_pct"], row["n_days"])
            icon = {"green": "🟢", "yellow": "🟡", "red": "🔴"}[g]
            st.write(
                f"{icon} **{row['time_window']}** — "
                f"{int(row['n_days'])} days, "
                f"{int(row['total_polls'])} polls, "
                f"{row['coverage_pct']:.0%} coverage"
            )
        st.plotly_chart(
            coverage_heatmap(daily_df, period),
            use_container_width=True,
            key=f"heatmap_{period}",
        )

st.caption(
    f"Comparing **{n_matched}** matched day-of-week × window cells "
    f"(Period A: {matched_days_a} days, Period B: {matched_days_b} days)"
)

if n_matched == 0:
    st.error("No matched cells between the two periods. Adjust the date ranges or windows.")
    st.stop()

# ── 3. Headline deltas ────────────────────────────────────────────────────────
st.subheader("Headline deltas")
deltas = headline_deltas(daily_df, metric_col, cells)

if deltas.empty:
    st.info("Not enough matched data to compute deltas.")
else:
    for window in sorted(deltas["time_window"].unique()):
        st.markdown(f"**{window} peak**")
        w_df = deltas[deltas["time_window"] == window]
        cols = st.columns(len(w_df))
        for i, (_, row) in enumerate(w_df.iterrows()):
            delta_s = row["delta"]
            delta_pct = row["delta_pct"]
            with cols[i]:
                st.metric(
                    label=f"{row['direction']} — {metric_label}",
                    value=f"{row['median_b']:.0f}s",
                    delta=f"{delta_s:+.0f}s ({delta_pct:+.1f}%)",
                    delta_color="inverse",
                )
                st.caption(f"Period A: {row['median_a']:.0f}s | Period B: {row['median_b']:.0f}s")

# ── 4. Time-of-day profile ────────────────────────────────────────────────────
st.subheader("Time-of-day profile")

if slot_df.empty:
    st.info("No slot-level data for the selected filters.")
else:
    for window_label in selected_window_labels:
        window = window_map[window_label]
        fig = profile_chart(
            slot_df,
            window=window,
            directions=selected_dirs,
            metric_col=slot_metric_col,
            metric_label=metric_label,
            bin_minutes=bin_minutes,
        )
        st.plotly_chart(fig, use_container_width=True, key=f"profile_{window}")
