import streamlit as st
from stmsn_query import connect
import pandas as pd
from datetime import date


@st.cache_resource
def get_con():
    return connect(
        key_id=st.secrets.get("STMSN_GCS_KEY_ID") or None,
        secret=st.secrets.get("STMSN_GCS_SECRET") or None,
    )


@st.cache_data(ttl=3600)
def load_date_range() -> tuple[date, date]:
    """Returns (first_date, last_date) across the agg table."""
    con = get_con()
    row = con.sql("SELECT MIN(request_date_local), MAX(request_date_local) FROM gold.agg_route_traffic_daily").fetchone()
    return row[0], row[1]


@st.cache_data(ttl=3600)
def load_routes() -> pd.DataFrame:
    """Loads dim_route once per session. Columns: route_name, corridor, direction, encoded_polyline."""
    con = get_con()
    return con.sql("SELECT route_name, corridor, direction, encoded_polyline FROM silver.dim_route").df()


@st.cache_data(ttl=900)
def load_daily(
    route_names: tuple[str, ...],
    period_a: tuple[str, str],
    period_b: tuple[str, str],
    windows: tuple[str, ...],
    include_weekends: bool,
) -> pd.DataFrame:
    """
    Loads agg_route_traffic_daily for both periods joined with dim_route for direction.
    Returns one DataFrame with a 'period' column ('A' or 'B').
    """
    con = get_con()
    names_sql = ", ".join(f"'{n}'" for n in route_names)
    wins_sql = ", ".join(f"'{w}'" for w in windows)

    weekend_filter = "" if include_weekends else "AND a.is_weekday AND NOT a.is_holiday"

    query = f"""
        SELECT
            a.route_name,
            d.corridor,
            d.direction,
            a.request_date_local,
            DAYNAME(a.request_date_local) AS day_of_week_name,
            a.time_window,
            a.is_weekday,
            a.is_holiday,
            a.poll_count,
            a.expected_poll_count,
            a.coverage_pct,
            a.delay_median,
            a.delay_p25,
            a.delay_p75,
            a.delay_p95,
            a.duration_median,
            a.duration_p25,
            a.duration_p75,
            a.duration_p95,
            CASE
                WHEN a.request_date_local BETWEEN '{period_a[0]}' AND '{period_a[1]}' THEN 'A'
                WHEN a.request_date_local BETWEEN '{period_b[0]}' AND '{period_b[1]}' THEN 'B'
            END AS period
        FROM gold.agg_route_traffic_daily a
        JOIN silver.dim_route d USING (route_name)
        WHERE a.route_name IN ({names_sql})
          AND a.time_window IN ({wins_sql})
          AND (
              a.request_date_local BETWEEN '{period_a[0]}' AND '{period_a[1]}'
              OR a.request_date_local BETWEEN '{period_b[0]}' AND '{period_b[1]}'
          )
          {weekend_filter}
    """
    df = con.sql(query).df()
    df = df[df["period"].notna()]
    return df


@st.cache_data(ttl=900)
def load_slots(
    route_names: tuple[str, ...],
    period_a: tuple[str, str],
    period_b: tuple[str, str],
    windows: tuple[str, ...],
    include_weekends: bool,
) -> pd.DataFrame:
    """
    Loads fact_route_traffic at slot_local grain for time-of-day profile.
    Returns one DataFrame with a 'period' column.
    """
    con = get_con()
    names_sql = ", ".join(f"'{n}'" for n in route_names)
    wins_sql = ", ".join(f"'{w}'" for w in windows)

    weekend_filter = "" if include_weekends else "AND is_weekday AND NOT is_holiday"

    query = f"""
        SELECT
            route_name,
            direction,
            corridor,
            request_date_local,
            day_of_week_name,
            slot_local,
            time_window,
            is_weekday,
            is_holiday,
            delay_seconds,
            duration_seconds,
            travel_time_index,
            CASE
                WHEN request_date_local BETWEEN '{period_a[0]}' AND '{period_a[1]}' THEN 'A'
                WHEN request_date_local BETWEEN '{period_b[0]}' AND '{period_b[1]}' THEN 'B'
            END AS period
        FROM silver.fact_route_traffic
        WHERE route_name IN ({names_sql})
          AND time_window IN ({wins_sql})
          AND (
              request_date_local BETWEEN '{period_a[0]}' AND '{period_a[1]}'
              OR request_date_local BETWEEN '{period_b[0]}' AND '{period_b[1]}'
          )
          {weekend_filter}
    """
    df = con.sql(query).df()
    df = df[df["period"].notna()]
    return df
