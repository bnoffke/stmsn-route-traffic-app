import streamlit as st
from stmsn_route_traffic_app.data import load_routes

st.set_page_config(page_title="STMSN Route Traffic", layout="wide")

routes_df = load_routes()
corridors = sorted(routes_df["corridor"].unique())

with st.sidebar:
    st.selectbox("Corridor", corridors, key="corridor")

pg = st.navigation(
    [
        st.Page("pages/daily_monitor.py", title="Daily Monitor", default=True),
        st.Page("pages/period_comparison.py", title="Time Period Comparison"),
    ],
    position="top",
)
pg.run()
