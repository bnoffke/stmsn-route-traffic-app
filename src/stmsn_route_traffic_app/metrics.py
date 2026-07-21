import pandas as pd
import numpy as np

METRICS = {
    "Delay (seconds)": "delay_median",
    "Duration (seconds)": "duration_median",
}

# Column names in agg table for p25/p75 per metric
METRIC_BANDS = {
    "delay_median": ("delay_p25", "delay_p75"),
    "duration_median": ("duration_p25", "duration_p75"),
}

# Column in fact table for slot-level data
SLOT_METRICS = {
    "Delay (seconds)": "delay_seconds",
    "Duration (seconds)": "duration_seconds",
}


def matched_cells(df: pd.DataFrame) -> set[tuple[str, str]]:
    """
    Returns the set of (day_of_week_name, time_window) cells present in BOTH periods.
    This is the anti-cherry-picking anchor — every downstream comparison filters to these.
    """
    if df.empty or "period" not in df.columns:
        return set()
    cells_a = set(zip(df[df["period"] == "A"]["day_of_week_name"], df[df["period"] == "A"]["time_window"]))
    cells_b = set(zip(df[df["period"] == "B"]["day_of_week_name"], df[df["period"] == "B"]["time_window"]))
    return cells_a & cells_b


def filter_to_matched(df: pd.DataFrame, cells: set[tuple[str, str]]) -> pd.DataFrame:
    if not cells:
        return df.iloc[0:0]
    mask = pd.Series(
        list(zip(df["day_of_week_name"], df["time_window"])),
        index=df.index,
    ).isin(cells)
    return df[mask]


def coverage_summary(df: pd.DataFrame, period: str) -> pd.DataFrame:
    """
    Per time_window: distinct days, total polls, coverage_pct (mean observed/expected).
    Returns a DataFrame indexed by time_window.
    """
    sub = df[df["period"] == period]
    if sub.empty:
        return pd.DataFrame(columns=["n_days", "total_polls", "coverage_pct"])
    return (
        sub.groupby("time_window")
        .agg(
            n_days=("request_date_local", "nunique"),
            total_polls=("poll_count", "sum"),
            coverage_pct=("coverage_pct", "mean"),
        )
        .reset_index()
    )


def grade(coverage_pct: float, n_days: int) -> str:
    """Returns 'green', 'yellow', or 'red' for badge coloring."""
    if n_days < 5 or coverage_pct < 0.60:
        return "red"
    if n_days >= 10 and coverage_pct >= 0.90:
        return "green"
    return "yellow"


def headline_deltas(df: pd.DataFrame, metric_col: str, cells: set) -> pd.DataFrame:
    """
    Per direction × time_window: median_a, median_b, delta_seconds, delta_pct.
    Only computed over matched cells.
    """
    matched = filter_to_matched(df, cells)
    if matched.empty:
        return pd.DataFrame()

    rows = []
    for (direction, window), grp in matched.groupby(["direction", "time_window"]):
        a_vals = grp[grp["period"] == "A"][metric_col]
        b_vals = grp[grp["period"] == "B"][metric_col]
        if a_vals.empty or b_vals.empty:
            continue
        med_a = float(np.median(a_vals))
        med_b = float(np.median(b_vals))
        delta = med_b - med_a
        delta_pct = (delta / med_a * 100) if med_a != 0 else float("nan")
        rows.append({
            "direction": direction,
            "time_window": window,
            "median_a": med_a,
            "median_b": med_b,
            "delta": delta,
            "delta_pct": delta_pct,
        })
    return pd.DataFrame(rows)
