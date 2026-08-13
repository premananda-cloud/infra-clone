# Berlin Open Data → BlenderGIS Pipeline

Fetch Berlin's open geodata with pure Python and import it into Blender via BlenderGIS — no QGIS needed.
Works on Windows, macOS, and Linux — the default path (`--source osm`) is pure Python with no
external binaries required.

---

## Install

```bash
pip install -r requirements.txt
```

That's the full dependency list — it's a pinned, tested set (`pip freeze` output), so versions
won't drift underneath you.

---

## Quick Start

```bash
cd src

# 1. Fetch Mitte district (OSM via Overpass — fastest, works on any OS)
python berlin_gis_pipeline.py --area mitte --source osm

# 2. Clean + optimize for Blender (merges layers, fixes geometry, adds mat_id)
python berlin_postprocess.py

# → output/*_clean.gpkg is ready to import into BlenderGIS (see "BlenderGIS Import Steps" below)
```

That's the whole pipeline for the standard path. Everything below is optional depending on how
you want to get the data into Blender, or if you want offline/official-cadaster sources.

---

## Two Ways to Get This Into Blender

**Path A — Direct `.gpkg` import (simplest, fewest steps)**
Import the `*_clean.gpkg` files straight into Blender with the BlenderGIS addon. See
[BlenderGIS Import Steps](#blendergis-import-steps) below.

**Path B — Shapefile + GeoTIFF (if BlenderGIS's native GPKG import gives you trouble, or you want
raster masks for shading/displacement)**

```bash
python berlin_to_blender.py --input ./output --res 1.0
```

This reads the `*_clean.gpkg` files and produces:

```
output/shp/   berlin_buildings.shp, berlin_roads.shp, berlin_water.shp, berlin_landuse.shp, berlin_parcels.shp
output/tif/   berlin_building_height.tif   ← height_m burned to raster (usable as displacement)
              berlin_building_mask.tif     ← binary building footprint mask
              berlin_roads_mask.tif        ← road presence mask
              berlin_water_mask.tif        ← water mask
              berlin_landuse_class.tif     ← mat_id class raster (0–8) for a Color Ramp shader
              berlin_ground_mask.tif       ← combined footprint mask (all features)
output/blendergis_import_guide.json        ← machine-readable import order + tips (mirrors this README)
```

Import the `.shp` files the same way as the `.gpkg` files (same import order, same
`height_m`/`mat_id` fields). Use the `.tif` rasters as texture inputs in the Shader Editor.

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

## Geofabrik PBF Method (full city / offline / optional)

This path is only needed for the full city or when Overpass is slow — the default
`--source osm` path above already works everywhere without it. It requires `osmium-tool`,
a native binary:

```bash
# 1. Download the Berlin extract (~70MB)
#    Windows: download the .pbf directly from the URL below instead of using wget
wget https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf

# 2. Install osmium-tool
sudo apt install osmium-tool              # Ubuntu/Debian
brew install osmium-tool                  # macOS
conda install -c conda-forge osmium-tool  # Windows (no official native .exe — conda-forge or WSL is the reliable route)

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
