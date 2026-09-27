"""DEMO data for the starter app.

Everything here is FAKE, hand-made example data placed near the Cam Pha coal-mining
area in Quang Ninh so the map has something to show. Replace it with Person 1's real
change regions (same property names) once their model produces georeferenced output.
"""

AOI = {
    "type": "FeatureCollection",
    "features": [{
        "type": "Feature",
        "properties": {"name": "Quang Ninh study area (Cam Pha, demo)", "source": "demo"},
        "geometry": {"type": "Polygon", "coordinates": [[
            [107.22, 20.98], [107.40, 20.98], [107.40, 21.10], [107.22, 21.10], [107.22, 20.98]
        ]]},
    }],
}

# Evidence fields use exactly the same names as the Person 2 notebook's evidence JSON.
_REGIONS = [
    # id, polygon ring, area_ha, mean_conf, dNDVI, dNDBI, dMNDWI, location
    ("r1", [[107.300, 21.040], [107.322, 21.043], [107.330, 21.055], [107.312, 21.060], [107.298, 21.052]], 182.4, 0.86, -0.34, 0.21, -0.03, "north-east"),
    ("r2", [[107.335, 21.030], [107.352, 21.031], [107.356, 21.042], [107.340, 21.045]], 96.1, 0.72, -0.18, 0.12, 0.01, "east"),
    ("r3", [[107.250, 21.000], [107.262, 21.001], [107.264, 21.010], [107.251, 21.011]], 41.7, 0.55, 0.04, 0.03, 0.16, "south-west"),
    ("r4", [[107.275, 21.070], [107.286, 21.071], [107.287, 21.079], [107.276, 21.080]], 28.3, 0.41, -0.07, 0.05, -0.02, "north"),
    ("r5", [[107.360, 21.000], [107.372, 21.002], [107.371, 21.012], [107.359, 21.010]], 19.9, 0.33, 0.02, -0.01, 0.00, "south-east"),
]

CHANGE_REGIONS = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "id": i + 1,
            "properties": {
                "id": rid, "area_ha": area, "mean_conf": conf,
                "dNDVI": dndvi, "dNDBI": dndbi, "dMNDWI": dmndwi,
                "location": loc, "date_before": "2018", "date_after": "2022", "source": "demo",
            },
            "geometry": {"type": "Polygon", "coordinates": [ring + [ring[0]]]},
        }
        for i, (rid, ring, area, conf, dndvi, dndbi, dmndwi, loc) in enumerate(_REGIONS)
    ],
}

AOI_AREA_HA = 24830  # area of the demo AOI box (~18.7 km x 13.3 km) in hectares


def evidence_for(region_ids):
    """Build an evidence JSON (same shape as the notebook) for the selected regions."""
    feats = [f["properties"] for f in CHANGE_REGIONS["features"] if f["properties"]["id"] in region_ids]
    total = sum(p["area_ha"] for p in feats)
    return {
        "pair_id": "quang_ninh_demo",
        "dates": ["2018", "2022"],
        "source": "demo",
        "change_frac": round(total / AOI_AREA_HA, 4),
        "regions": [
            {k: p[k] for k in ("id", "location", "area_ha", "mean_conf", "dNDVI", "dNDBI", "dMNDWI")}
            for p in sorted(feats, key=lambda p: -p["area_ha"])
        ],
    }
