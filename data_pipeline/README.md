# Berlin Open Data → BlenderGIS Pipeline

Fetch Berlin's open geodata with pure Python and import it into Blender via BlenderGIS — no QGIS needed.

---

## Install

```bash
pip install requests geopandas shapely pyproj fiona osmnx tqdm
```

---

## Quick Start

```bash
# Fetch Mitte district (OSM, fastest)
python berlin_gis_pipeline.py --area mitte --source osm

# Clean + optimize for Blender
python berlin_postprocess.py

# → Import *_clean.gpkg files into BlenderGIS
```

---

## Data Sources

| Source | Script flag | What you get |
|---|---|---|
| **OSM / Overpass** | `--source osm` | Buildings (heights), roads, water, landuse |
| **ALKIS WFS** | `--source alkis` | Official cadaster footprints + parcels |
| **ATKIS WFS** | `--source atkis` | Authoritative road axes |
| **All combined** | `--source all` | Everything (ALKIS + OSM merged) |

---

## Area Presets

| Preset | Coverage |
|---|---|
| `mitte` | Berlin Mitte (default) |
| `prenzlauer` | Prenzlauer Berg |
| `kreuzberg` | Kreuzberg |
| `tiergarten` | Tiergarten |
| `alexanderplatz` | Alexanderplatz vicinity |
| `potsdamer` | Potsdamer Platz |
| `full_city` | All of Berlin (large — use PBF method) |

Custom bbox: `--area "13.38,52.50,13.42,52.53"` (minLon,minLat,maxLon,maxLat)

---

## Geofabrik PBF Method (full city / offline)

For the full city or when Overpass is slow:

```bash
# 1. Download the Berlin extract (~70MB)
wget https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf

# 2. Install osmium-tool
sudo apt install osmium-tool    # Ubuntu/Debian
brew install osmium-tool        # macOS

# 3. Extract your area from the PBF
python berlin_pbf_extractor.py --pbf berlin-latest.osm.pbf --area mitte

# 4. Post-process
python berlin_postprocess.py
```

---

## Output Files

After running the pipeline + post-processor:

```
output/
├── berlin_buildings_clean.gpkg   ← 3D buildings (extrude by height_m)
├── berlin_roads_clean.gpkg       ← Road network
├── berlin_water_clean.gpkg       ← Rivers, lakes, canals
├── berlin_landuse_clean.gpkg     ← Parks, forests, zones
├── berlin_parcels_clean.gpkg     ← Land parcels (ALKIS)
├── berlin_terrain_bbox.geojson   ← For DEM alignment
└── blendergis_info.json          ← Scene CRS + centroid info
```

**Key attributes:**
- `height_m` — building height in metres (for extrusion)
- `mat_id` — integer material index (0–N) for Blender shader assignment
- `building_type` — OSM building tag
- `road_type` — highway classification

---

## BlenderGIS Import Steps

1. Open Blender → **N panel → GIS**
2. **Scene CRS** → Set to `EPSG:25833` (ETRS89 / UTM zone 33N)
3. **GIS > Import > GIS file** — import in this order (bottom layer first):
   1. `berlin_landuse_clean.gpkg` — Type: Polygon, flat
   2. `berlin_water_clean.gpkg` — Type: Polygon, flat
   3. `berlin_parcels_clean.gpkg` — Type: Polygon, flat
   4. `berlin_roads_clean.gpkg` — Type: Line
   5. `berlin_buildings_clean.gpkg` — Type: Polygon, **Extrude field: `height_m`**
4. **DEM (optional):** GIS > Get elevation (SRTM) → use extent from `berlin_terrain_bbox.geojson`

---

## Blender Material Setup (using mat_id)

In Blender's shader editor:
```
Attribute node ("mat_id") → Math → Compare → Material output
```

Or use a **Color Ramp** driven by `mat_id` to assign distinct colors per building type automatically.

---

## Tips

- **Performance:** For large areas, reduce polygon count with `--simplify 1.0` in post-processor
- **Heights:** OSM has `height` tags for ~30% of Berlin buildings; the rest use level×3m estimate
- **ALKIS accuracy:** Berlin's WFS requires the IP to be within Germany or use a VPN for some layers
- **CRS matters:** Always use EPSG:25833 — BlenderGIS needs a metric CRS for real-world scale

---

## WFS Endpoints Reference

| Dataset | URL |
|---|---|
| ALKIS buildings | `https://fbinter.stadt-berlin.de/fb/wfs/geometry/senstadt/re_alkis_vereinf/` |
| ATKIS Basis-DLM | `https://fbinter.stadt-berlin.de/fb/wfs/data/senstadt/s_wfs_alkis` |
| WFS Explorer | `https://fbinter.stadt-berlin.de/fb/index.jsp` |
| Geofabrik Berlin | `https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf` |
| Overpass API | `https://overpass-api.de/api/interpreter` |
