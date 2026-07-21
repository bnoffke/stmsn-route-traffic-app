import streamlit as st
from datetime import date
from streamlit_folium import st_folium

from stmsn_route_traffic_app.data import load_routes, load_slots_all, load_date_range
from stmsn_route_traffic_app.charts import daily_profile_chart
from stmsn_route_traffic_app.mapview import corridor_map

WINDOWS = ("AM", "PM")


# ── Shared state ──────────────────────────────────────────────────────────────
routes_df = load_routes()
corridor = st.session_state.get("corridor", sorted(routes_df["corridor"].unique())[0])
corridor_routes = routes_df[routes_df["corridor"] == corridor]
all_dirs = sorted(corridor_routes["direction"].unique())
corridor_route_names = tuple(corridor_routes["route_name"].tolist())

# ── Sidebar controls ─────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Daily Monitor")
    data_start, _ = load_date_range()
    selected_date = st.date_input(
        "Day",
        value=date.today(),
        min_value=data_start,
        max_value=date.today(),
        key="monitor_day",
    )
    if st.button("Refresh data", use_container_width=True):
        load_slots_all.clear()
        st.rerun()

    with st.expander("Filter historical data", expanded=False):
        hist_range = st.date_input(
            "Date range",
            value=(data_start, date.today()),
            min_value=data_start,
            max_value=date.today(),
            key="hist_date_range",
        )
        include_holidays = st.toggle("Include holidays", value=False, key="hist_holidays")

    with st.popover("View corridor map", use_container_width=True):
        m = corridor_map(routes_df, list(corridor_route_names))
        st_folium(m, height=320, use_container_width=True, returned_objects=[])

# ── Load all slot data for corridor (no date filter) ─────────────────────────
slot_df = load_slots_all(corridor_route_names, WINDOWS)

# Apply historical reference filters in-dataframe
hist_df = slot_df.copy()
if isinstance(hist_range, tuple) and len(hist_range) == 2:
    hist_df = hist_df[
        (hist_df["request_date_local"] >= str(hist_range[0])) &
        (hist_df["request_date_local"] <= str(hist_range[1])) &
        (hist_df["request_date_local"] != str(selected_date))
    ]
if not include_holidays:
    hist_df = hist_df[hist_df["is_holiday"] != True]

# ── Top row ───────────────────────────────────────────────────────────────────
st.subheader(f"Corridor: {corridor}")

selected_date_str = str(selected_date)
dow_name = selected_date.strftime("%A")

# Weekday counts from full dataset
same_dow_dates = hist_df[hist_df["day_of_week_name"] == dow_name]["request_date_local"].unique()
n_same_dow_total = len(same_dow_dates)

# Per-window/direction medians for selected day
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

# ── Charts: AM then PM, NB | SB ───────────────────────────────────────────────
if day_rows.empty:
    st.info(f"No data for {selected_date_str}. Select a different day.")
else:
    for window in WINDOWS:
        st.subheader(f"{window} peak")
        cols = st.columns(len(all_dirs))
        for i, direction in enumerate(all_dirs):
            with cols[i]:
                fig = daily_profile_chart(slot_df, selected_date_str, window, direction, hist_df=hist_df)
                st.plotly_chart(fig, use_container_width=True, key=f"daily_{window}_{direction}")
