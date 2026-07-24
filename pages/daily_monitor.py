import streamlit as st
from datetime import timedelta
from streamlit_folium import st_folium

from stmsn_route_traffic_app.data import load_routes, load_slots_all, load_date_range
from stmsn_route_traffic_app.charts import daily_profile_chart, weekly_profile_chart
from stmsn_route_traffic_app.mapview import corridor_map
from stmsn_route_traffic_app.util import chicago_today, week_bounds

WINDOWS = ("AM", "PM")


# ── Shared state ──────────────────────────────────────────────────────────────
routes_df = load_routes()
corridor = st.session_state.get("corridor", sorted(routes_df["corridor"].unique())[0])
corridor_routes = routes_df[routes_df["corridor"] == corridor]
all_dirs = sorted(corridor_routes["direction"].unique())
corridor_route_names = tuple(corridor_routes["route_name"].tolist())

# ── Load all slot data (needed before sidebar so we can show data freshness) ──
slot_df = load_slots_all(corridor_route_names, WINDOWS)

# Data freshness: max date + max slot on that date
if not slot_df.empty:
    latest_date = str(slot_df["request_date_local"].max())[:10]
    latest_slot = slot_df[slot_df["request_date_local"] == latest_date]["slot_local"].max()
    freshness_label = f"Data through: {latest_date} {latest_slot} CT"
else:
    freshness_label = "No data loaded"

# ── Sidebar controls ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Daily Monitor")
    data_start, _ = load_date_range()
    today_ct = chicago_today()
    selected_date = st.date_input(
        "Day",
        value=today_ct,
        min_value=data_start,
        max_value=today_ct,
        key="monitor_day",
        help="Also determines the week shown on the Daily View tab.",
    )
    if st.button("Refresh data", use_container_width=True):
        load_slots_all.clear()
        st.rerun()
    st.caption(freshness_label)

    with st.expander("Filter historical data", expanded=False):
        hist_range = st.date_input(
            "Date range",
            value=(data_start, today_ct),
            min_value=data_start,
            max_value=today_ct,
            key="hist_date_range",
        )
        include_holidays = st.toggle("Include holidays", value=False, key="hist_holidays")

    with st.popover("View corridor map", use_container_width=True):
        m = corridor_map(routes_df, list(corridor_route_names))
        st_folium(m, height=320, use_container_width=True, returned_objects=[])

# ── Resolve hist_range endpoints ─────────────────────────────────────────────
if isinstance(hist_range, tuple) and len(hist_range) == 2:
    hist_range_start = hist_range[0]
    hist_range_end = hist_range[1]
else:
    hist_range_start = data_start
    hist_range_end = today_ct

selected_date_str = str(selected_date)
week_start, week_end = week_bounds(selected_date)
week_start_str = str(week_start)

# ── Real Time View historical pool ────────────────────────────────────────────
# Cap at strictly before selected date so the pool is always "historical"
hist_df = slot_df[
    (slot_df["request_date_local"] >= str(hist_range_start)) &
    (slot_df["request_date_local"] < selected_date_str)
].copy()
if not include_holidays:
    hist_df = hist_df[hist_df["is_holiday"] != True]

# ── Daily View historical pool ────────────────────────────────────────────────
# Snap hist_range to week boundaries (start → Monday, end → Sunday of chosen week)
# then cap at the day before the selected week.
snap_start = hist_range_start - timedelta(days=hist_range_start.weekday())
snap_end_raw = hist_range_end
snap_end = snap_end_raw + timedelta(days=6 - snap_end_raw.weekday())
effective_end = min(snap_end, week_start - timedelta(days=1))

week_hist_df = slot_df[
    (slot_df["request_date_local"] >= str(snap_start)) &
    (slot_df["request_date_local"] <= str(effective_end))
].copy()
if not include_holidays:
    week_hist_df = week_hist_df[week_hist_df["is_holiday"] != True]

# ── Top row ───────────────────────────────────────────────────────────────────
st.subheader(f"Corridor: {corridor}")

tab_rt, tab_daily = st.tabs(["Real Time View", "Daily View"])

# ── Real Time View tab ────────────────────────────────────────────────────────
with tab_rt:
    dow_name = selected_date.strftime("%A")

    same_dow_dates = hist_df[hist_df["day_of_week_name"] == dow_name]["request_date_local"].unique()
    n_same_dow_total = len(same_dow_dates)

    day_rows = slot_df[slot_df["request_date_local"] == selected_date_str]

    def day_median(window, direction):
        sub = day_rows[(day_rows["time_window"] == window) & (day_rows["direction"] == direction)]
        return f"{sub['duration_seconds'].median():.0f}s" if not sub.empty else "—"

    metric_cols = [("Day of week", dow_name), (f"{dow_name}s in data", str(n_same_dow_total))] + [
        (f"{w} {d} Median", day_median(w, d)) for w in WINDOWS for d in all_dirs
    ]
    cols = st.columns(len(metric_cols))
    for col, (label, value) in zip(cols, metric_cols):
        with col:
            st.metric(label, value)

    if day_rows.empty:
        st.info(f"No data for {selected_date_str}. Select a different day.")
    else:
        for window in WINDOWS:
            st.subheader(f"{window} peak")
            cols = st.columns(len(all_dirs))
            for i, direction in enumerate(all_dirs):
                with cols[i]:
                    fig = daily_profile_chart(slot_df, selected_date_str, window, direction, hist_df=hist_df)
                    st.plotly_chart(fig, use_container_width=True, key=f"rt_{window}_{direction}", config={"displayModeBar": False, "scrollZoom": False})

# ── Daily View tab ────────────────────────────────────────────────────────────
with tab_daily:
    week_rows = slot_df[
        (slot_df["request_date_local"] >= week_start_str) &
        (slot_df["request_date_local"] <= str(week_end))
    ]

    n_hist_days = week_hist_df["request_date_local"].nunique()

    def week_median(window, direction):
        sub = week_rows[(week_rows["time_window"] == window) & (week_rows["direction"] == direction)]
        return f"{sub['duration_seconds'].median():.0f}s" if not sub.empty else "—"

    week_metric_cols = [
        ("Week of", week_start.strftime("%b %-d, %Y")),
        ("Historical days", str(n_hist_days)),
    ] + [
        (f"{w} {d} Median", week_median(w, d)) for w in WINDOWS for d in all_dirs
    ]
    cols = st.columns(len(week_metric_cols))
    for col, (label, value) in zip(cols, week_metric_cols):
        with col:
            st.metric(label, value)

    for window in WINDOWS:
        st.subheader(f"{window} peak")
        cols = st.columns(len(all_dirs))
        for i, direction in enumerate(all_dirs):
            with cols[i]:
                fig = weekly_profile_chart(slot_df, week_start, week_end, window, direction, hist_df=week_hist_df)
                st.plotly_chart(fig, use_container_width=True, key=f"daily_{window}_{direction}", config={"displayModeBar": False, "scrollZoom": False})
