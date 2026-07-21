import folium
import polyline as pl
import pandas as pd

DIRECTION_COLORS = {"NB": "#1f77b4", "SB": "#ff7f0e"}
DEFAULT_COLOR = "#888888"


def corridor_map(routes_df: pd.DataFrame, route_names: list[str]) -> folium.Map:
    """
    Renders a folium map with PolyLines for each selected route_name, colored by direction.
    """
    selected = routes_df[routes_df["route_name"].isin(route_names)]

    m = folium.Map(tiles="CartoDB positron", zoom_start=13)

    all_coords = []
    for _, row in selected.iterrows():
        if not row.get("encoded_polyline"):
            continue
        coords = pl.decode(row["encoded_polyline"])
        all_coords.extend(coords)
        color = DIRECTION_COLORS.get(row.get("direction", ""), DEFAULT_COLOR)
        folium.PolyLine(
            coords,
            color=color,
            weight=5,
            opacity=0.8,
            tooltip=f"{row.get('corridor', '')} {row.get('direction', '')}",
        ).add_to(m)

    if all_coords:
        lats = [c[0] for c in all_coords]
        lons = [c[1] for c in all_coords]
        m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])

    m.get_root().html.add_child(folium.Element(
        '<style>.leaflet-control-attribution { font-size: 8px !important; opacity: 0.5; }</style>'
    ))

    # Simple legend via HTML
    legend_html = """
    <div style="position: fixed; bottom: 30px; left: 30px; z-index: 1000;
                background: white; padding: 8px 12px; border-radius: 6px;
                border: 1px solid #ccc; font-size: 13px; line-height: 1.8;">
    """
    for direction, color in DIRECTION_COLORS.items():
        legend_html += f'<span style="color:{color};">&#9644;</span> <span style="color:#000;">{direction}</span><br>'
    legend_html += "</div>"
    m.get_root().html.add_child(folium.Element(legend_html))

    return m
