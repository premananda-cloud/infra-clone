"""
Berlin Open Source GIS Pipeline → BlenderGIS
============================================
Fetches data from:
  - OSM via Overpass API (buildings with heights, roads, water, landuse)
  - ALKIS Berlin WFS (official building footprints & parcels)
  - ATKIS Basis-DLM WFS (topographic objects)
  - Geofabrik PBF fallback (full city extract)

Outputs to ./output/:
  berlin_buildings.gpkg      ← 3D buildings (LOD1/LOD2 where available)
  berlin_roads.gpkg          ← Road network
  berlin_water.gpkg          ← Water bodies
  berlin_landuse.gpkg        ← Land use / green areas
  berlin_parcels.gpkg        ← Land parcels (ALKIS)
  berlin_terrain_bbox.geojson← Bounding box for DEM alignment

Usage:
  pip install requests geopandas shapely pyproj fiona osmnx tqdm
  python berlin_gis_pipeline.py [--area mitte] [--source osm|alkis|all]
"""

import os, json, time, argparse, logging
from pathlib import Path

import requests
import geopandas as gpd
import pandas as pd
from shapely.geometry import shape, box, Point, mapping
from shapely.ops import unary_union
import pyproj
from pyproj import Transformer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# AREA PRESETS (bounding boxes in WGS84: minx, miny, maxx, maxy)
# ─────────────────────────────────────────────────────────────────────────────
AREA_PRESETS = {
    "mitte":        (13.3600, 52.5050, 13.4200, 52.5350),   # Berlin Mitte
    "prenzlauer":   (13.4100, 52.5250, 13.4600, 52.5500),   # Prenzlauer Berg
    "kreuzberg":    (13.3850, 52.4850, 13.4350, 52.5100),   # Kreuzberg
    "tiergarten":   (13.3300, 52.5050, 13.3800, 52.5200),   # Tiergarten
    "alexanderplatz": (13.4000, 52.5150, 13.4200, 52.5280), # Alexanderplatz area
    "potsdamer":    (13.3650, 52.5000, 13.3900, 52.5150),   # Potsdamer Platz
    "full_city":    (13.0900, 52.3400, 13.7600, 52.6800),   # All Berlin (large!)
}

# BlenderGIS works best in a metric CRS; ETRS89 / UTM zone 33N
TARGET_CRS = "EPSG:25833"

OUTPUT_DIR = Path("./output")
OUTPUT_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# UTILITY
# ─────────────────────────────────────────────────────────────────────────────

def bbox_to_overpass(bbox):
    """Convert (minx, miny, maxx, maxy) → Overpass south,west,north,east string."""
    minx, miny, maxx, maxy = bbox
    return f"{miny},{minx},{maxy},{maxx}"


def to_target_crs(gdf):
    """Reproject GeoDataFrame to TARGET_CRS."""
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    return gdf.to_crs(TARGET_CRS)


def save_layer(gdf, name, driver="GPKG"):
    """Save a GeoDataFrame to output directory."""
    ext = "gpkg" if driver == "GPKG" else "geojson"
    out = OUTPUT_DIR / f"{name}.{ext}"
    gdf.to_file(str(out), driver=driver)
    log.info(f"  ✓ Saved {name}.{ext}  ({len(gdf)} features)")
    return out


def overpass_query(ql, retries=3, delay=5):
    """Execute an Overpass QL query and return JSON."""
    url = "https://overpass-api.de/api/interpreter"
    for attempt in range(retries):
        try:
            r = requests.post(url, data={"data": ql}, timeout=120)
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            log.warning(f"Overpass attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    raise RuntimeError("Overpass API failed after retries")


def elements_to_gdf(elements, geom_type="polygon"):
    """Convert Overpass JSON elements → GeoDataFrame."""
    features = []
    node_map = {}

    # Build node lookup
    for el in elements:
        if el["type"] == "node":
            node_map[el["id"]] = (el["lon"], el["lat"])

    for el in elements:
        if el["type"] == "way" and "nodes" in el:
            coords = [node_map[n] for n in el["nodes"] if n in node_map]
            if len(coords) < 2:
                continue
            tags = el.get("tags", {})
            try:
                if geom_type == "polygon" and coords[0] == coords[-1] and len(coords) >= 4:
                    from shapely.geometry import Polygon
                    geom = Polygon(coords)
                elif geom_type == "line":
                    from shapely.geometry import LineString
                    geom = LineString(coords)
                else:
                    from shapely.geometry import LineString, Polygon
                    geom = Polygon(coords) if (coords[0] == coords[-1] and len(coords) >= 4) else LineString(coords)
                features.append({"geometry": geom, **tags, "osm_id": el["id"]})
            except Exception:
                pass

        elif el["type"] == "node" and geom_type == "point":
            from shapely.geometry import Point
            features.append({
                "geometry": Point(el["lon"], el["lat"]),
                **el.get("tags", {}),
                "osm_id": el["id"]
            })

    if not features:
        return gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

    gdf = gpd.GeoDataFrame(features, crs="EPSG:4326")
    gdf = gdf[gdf.geometry.notna()]
    gdf = gdf[~gdf.geometry.is_empty]
    return gdf


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 1: OSM via Overpass API
# ─────────────────────────────────────────────────────────────────────────────

def fetch_osm_buildings(bbox):
    """
    Fetch buildings from OSM with height attributes.
    Returns GeoDataFrame with columns: height, building_levels, building_type, roof_shape
    """
    log.info("Fetching OSM buildings via Overpass...")
    bb = bbox_to_overpass(bbox)
    ql = f"""
[out:json][timeout:90];
(
  way["building"]({bb});
  relation["building"]({bb});
);
out body;
>;
out skel qt;
"""
    data = overpass_query(ql)
    gdf = elements_to_gdf(data["elements"], geom_type="polygon")

    if gdf.empty:
        log.warning("No OSM buildings found in area")
        return gdf

    # Normalise height fields for BlenderGIS LOD1 extrusion
    def parse_height(row):
        # Try explicit height tag first
        for col in ["height", "building:height"]:
            if col in row and row[col]:
                try:
                    return float(str(row[col]).replace("m", "").strip())
                except ValueError:
                    pass
        # Estimate from levels (3m/floor)
        for col in ["building:levels", "levels"]:
            if col in row and row[col]:
                try:
                    return float(row[col]) * 3.0
                except ValueError:
                    pass
        # Default height by building type
        btype = row.get("building", "yes")
        defaults = {
            "yes": 9.0, "house": 7.0, "apartments": 18.0,
            "commercial": 12.0, "industrial": 8.0, "office": 24.0,
            "retail": 6.0, "church": 20.0, "cathedral": 35.0,
            "tower": 50.0, "skyscraper": 100.0,
        }
        return defaults.get(btype, 9.0)

    # Apply height estimation
    gdf["height_m"] = gdf.apply(parse_height, axis=1)
    gdf["min_height"] = gdf.get("min_height", 0)
    gdf["building_type"] = gdf.get("building", "yes")
    gdf["roof_shape"] = gdf.get("roof:shape", "flat")
    gdf["name"] = gdf.get("name", "")
    gdf["addr_street"] = gdf.get("addr:street", "")
    gdf["addr_housenumber"] = gdf.get("addr:housenumber", "")

    # Keep only relevant columns
    keep = ["geometry", "osm_id", "height_m", "min_height",
            "building_type", "roof_shape", "name", "addr_street", "addr_housenumber"]
    keep = [c for c in keep if c in gdf.columns]
    gdf = gdf[keep].copy()

    gdf = to_target_crs(gdf)
    log.info(f"  → {len(gdf)} buildings fetched")
    return gdf


def fetch_osm_roads(bbox):
    """Fetch road network from OSM."""
    log.info("Fetching OSM roads via Overpass...")
    bb = bbox_to_overpass(bbox)
    ql = f"""
[out:json][timeout:90];
(
  way["highway"~"motorway|trunk|primary|secondary|tertiary|residential|pedestrian|footway|cycleway|path|service|unclassified"]({bb});
);
out body;
>;
out skel qt;
"""
    data = overpass_query(ql)
    gdf = elements_to_gdf(data["elements"], geom_type="line")

    if gdf.empty:
        return gdf

    gdf["road_type"] = gdf.get("highway", "unclassified")
    gdf["road_name"] = gdf.get("name", "")
    gdf["lanes"] = gdf.get("lanes", "")
    gdf["surface"] = gdf.get("surface", "")

    keep = ["geometry", "osm_id", "road_type", "road_name", "lanes", "surface"]
    keep = [c for c in keep if c in gdf.columns]
    gdf = gdf[keep].copy()

    gdf = to_target_crs(gdf)
    log.info(f"  → {len(gdf)} road segments fetched")
    return gdf


def fetch_osm_water(bbox):
    """Fetch water bodies from OSM."""
    log.info("Fetching OSM water bodies via Overpass...")
    bb = bbox_to_overpass(bbox)
    ql = f"""
[out:json][timeout:60];
(
  way["natural"="water"]({bb});
  way["waterway"~"river|canal|stream|drain"]({bb});
  relation["natural"="water"]({bb});
);
out body;
>;
out skel qt;
"""
    data = overpass_query(ql)
    gdf = elements_to_gdf(data["elements"], geom_type="polygon")

    if gdf.empty:
        return gdf

    gdf["water_type"] = gdf.get("natural", gdf.get("waterway", "water"))
    gdf["water_name"] = gdf.get("name", "")

    keep = ["geometry", "osm_id", "water_type", "water_name"]
    keep = [c for c in keep if c in gdf.columns]
    gdf = gdf[keep].copy()

    gdf = to_target_crs(gdf)
    log.info(f"  → {len(gdf)} water features fetched")
    return gdf


def fetch_osm_landuse(bbox):
    """Fetch land use areas from OSM."""
    log.info("Fetching OSM land use via Overpass...")
    bb = bbox_to_overpass(bbox)
    ql = f"""
[out:json][timeout:60];
(
  way["landuse"~"park|forest|grass|meadow|residential|commercial|industrial|retail|cemetery|farmland|allotments"]({bb});
  way["leisure"~"park|garden|pitch|sports_centre"]({bb});
  relation["landuse"]({bb});
);
out body;
>;
out skel qt;
"""
    data = overpass_query(ql)
    gdf = elements_to_gdf(data["elements"], geom_type="polygon")

    if gdf.empty:
        return gdf

    gdf["landuse_type"] = gdf.get("landuse", gdf.get("leisure", "unknown"))
    gdf["area_name"] = gdf.get("name", "")

    keep = ["geometry", "osm_id", "landuse_type", "area_name"]
    keep = [c for c in keep if c in gdf.columns]
    gdf = gdf[keep].copy()

    gdf = to_target_crs(gdf)
    log.info(f"  → {len(gdf)} landuse polygons fetched")
    return gdf


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 2: Berlin ALKIS WFS (official cadaster)
# ─────────────────────────────────────────────────────────────────────────────

ALKIS_WFS_BASE = "https://fbinter.stadt-berlin.de/fb/wfs/geometry/senstadt/re_alkis_vereinf/"

def fetch_alkis_buildings(bbox):
    """
    Fetch official ALKIS building footprints from Berlin's WFS.
    These are more accurate than OSM for cadaster-level detail.
    """
    log.info("Fetching ALKIS buildings from Berlin WFS...")
    minx, miny, maxx, maxy = bbox

    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "re_alkis_vereinf:gebaeude",   # building layer
        "SRSNAME": "EPSG:25833",
        "BBOX": f"{minx},{miny},{maxx},{maxy},EPSG:4326",
        "COUNT": "5000",
        "OUTPUTFORMAT": "application/json",
    }

    try:
        r = requests.get(ALKIS_WFS_BASE, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        gdf = gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:25833")

        if gdf.empty:
            log.warning("ALKIS returned 0 buildings — bbox may need to be in ETRS89")
            return gdf

        # Map ALKIS fields to our schema
        rename_map = {
            "gebaeudefunktion": "building_type",
            "anzahlderoberirdischengeschosse": "building_levels",
            "name": "name",
        }
        for old, new in rename_map.items():
            if old in gdf.columns:
                gdf[new] = gdf[old]

        # Estimate height from levels
        if "building_levels" in gdf.columns:
            gdf["height_m"] = pd.to_numeric(gdf["building_levels"], errors="coerce").fillna(3) * 3.0
        else:
            gdf["height_m"] = 9.0

        log.info(f"  → {len(gdf)} ALKIS buildings fetched")
        return gdf

    except Exception as e:
        log.warning(f"ALKIS WFS failed: {e} — will use OSM buildings only")
        return gpd.GeoDataFrame(geometry=[], crs=TARGET_CRS)


def fetch_alkis_parcels(bbox):
    """Fetch ALKIS land parcels (Flurstücke)."""
    log.info("Fetching ALKIS parcels from Berlin WFS...")
    minx, miny, maxx, maxy = bbox

    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "re_alkis_vereinf:flurstueck",  # parcel layer
        "SRSNAME": "EPSG:25833",
        "BBOX": f"{minx},{miny},{maxx},{maxy},EPSG:4326",
        "COUNT": "5000",
        "OUTPUTFORMAT": "application/json",
    }

    try:
        r = requests.get(ALKIS_WFS_BASE, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        gdf = gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:25833")
        log.info(f"  → {len(gdf)} ALKIS parcels fetched")
        return gdf
    except Exception as e:
        log.warning(f"ALKIS parcels WFS failed: {e}")
        return gpd.GeoDataFrame(geometry=[], crs=TARGET_CRS)


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 3: ATKIS Basis-DLM WFS (topographic model)
# ─────────────────────────────────────────────────────────────────────────────

ATKIS_WFS_BASE = "https://fbinter.stadt-berlin.de/fb/wfs/data/senstadt/s_wfs_alkis"

def fetch_atkis_transport(bbox):
    """
    Fetch ATKIS transport network (roads, railways).
    More authoritative than OSM for infrastructure planning.
    """
    log.info("Fetching ATKIS transport network...")
    minx, miny, maxx, maxy = bbox

    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "s_wfs_alkis:ax_strassenachse",  # road axis
        "BBOX": f"{minx},{miny},{maxx},{maxy},EPSG:4326",
        "COUNT": "5000",
        "OUTPUTFORMAT": "application/json",
    }

    try:
        r = requests.get(ATKIS_WFS_BASE, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        gdf = gpd.GeoDataFrame.from_features(data["features"], crs="EPSG:25833")
        log.info(f"  → {len(gdf)} ATKIS transport features")
        return gdf
    except Exception as e:
        log.warning(f"ATKIS WFS failed: {e}")
        return gpd.GeoDataFrame(geometry=[], crs=TARGET_CRS)


# ─────────────────────────────────────────────────────────────────────────────
# TERRAIN BBOX EXPORT (for DEM alignment in BlenderGIS)
# ─────────────────────────────────────────────────────────────────────────────

def export_terrain_bbox(bbox, target_crs=TARGET_CRS):
    """
    Export the query bounding box as a GeoJSON polygon.
    BlenderGIS uses this to align the DEM terrain mesh.
    """
    log.info("Exporting terrain bounding box...")
    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    minx, miny, maxx, maxy = bbox
    poly = box(minx, miny, maxx, maxy)

    gdf = gpd.GeoDataFrame(
        [{"area": "query_bbox", "crs": target_crs, "geometry": poly}],
        crs="EPSG:4326"
    ).to_crs(target_crs)

    out = OUTPUT_DIR / "berlin_terrain_bbox.geojson"
    gdf.to_file(str(out), driver="GeoJSON")
    log.info(f"  ✓ Saved terrain_bbox.geojson")

    # Also export centroid info for BlenderGIS origin setting
    centroid = gdf.geometry.iloc[0].centroid
    info = {
        "centroid_x": centroid.x,
        "centroid_y": centroid.y,
        "crs": target_crs,
        "epsg": 25833,
        "bbox_wgs84": list(bbox),
        "blendergis_tip": (
            "In BlenderGIS: Set Scene CRS to EPSG:25833, "
            "then Import > GIS File for each .gpkg layer. "
            "Use 'berlin_terrain_bbox.geojson' to define your DEM extent."
        )
    }
    with open(OUTPUT_DIR / "blendergis_info.json", "w") as f:
        json.dump(info, f, indent=2)
    log.info(f"  ✓ Saved blendergis_info.json (centroid + tips)")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

def run_pipeline(area="mitte", source="osm"):
    bbox = AREA_PRESETS.get(area)
    if bbox is None:
        # Try parsing as "minx,miny,maxx,maxy"
        try:
            bbox = tuple(map(float, area.split(",")))
            assert len(bbox) == 4
        except Exception:
            raise ValueError(f"Unknown area '{area}'. Choose from: {list(AREA_PRESETS.keys())} or pass minx,miny,maxx,maxy")

    log.info(f"═══════════════════════════════════════════")
    log.info(f"Berlin GIS Pipeline")
    log.info(f"  Area   : {area}")
    log.info(f"  BBox   : {bbox}")
    log.info(f"  Source : {source}")
    log.info(f"  CRS    : {TARGET_CRS}")
    log.info(f"  Output : {OUTPUT_DIR.resolve()}")
    log.info(f"═══════════════════════════════════════════")

    results = {}

    # ── OSM layers (always fetch; best coverage) ──────────────────────────
    if source in ("osm", "all"):
        buildings = fetch_osm_buildings(bbox)
        if not buildings.empty:
            save_layer(buildings, "berlin_buildings")
            results["buildings"] = buildings

        roads = fetch_osm_roads(bbox)
        if not roads.empty:
            save_layer(roads, "berlin_roads")
            results["roads"] = roads

        water = fetch_osm_water(bbox)
        if not water.empty:
            save_layer(water, "berlin_water")
            results["water"] = water

        landuse = fetch_osm_landuse(bbox)
        if not landuse.empty:
            save_layer(landuse, "berlin_landuse")
            results["landuse"] = landuse

    # ── ALKIS (official cadaster) ─────────────────────────────────────────
    if source in ("alkis", "all"):
        alkis_buildings = fetch_alkis_buildings(bbox)
        if not alkis_buildings.empty:
            save_layer(alkis_buildings, "berlin_alkis_buildings")
            results["alkis_buildings"] = alkis_buildings

        alkis_parcels = fetch_alkis_parcels(bbox)
        if not alkis_parcels.empty:
            save_layer(alkis_parcels, "berlin_parcels")
            results["alkis_parcels"] = alkis_parcels

    # ── ATKIS (topographic) ───────────────────────────────────────────────
    if source in ("atkis", "all"):
        atkis_roads = fetch_atkis_transport(bbox)
        if not atkis_roads.empty:
            save_layer(atkis_roads, "berlin_atkis_roads")
            results["atkis_roads"] = atkis_roads

    # ── Terrain bbox (always) ─────────────────────────────────────────────
    export_terrain_bbox(bbox)

    # ── Summary ───────────────────────────────────────────────────────────
    log.info("")
    log.info("═══════════════════════════════════════════")
    log.info("PIPELINE COMPLETE — OUTPUT FILES:")
    for f in sorted(OUTPUT_DIR.iterdir()):
        size_kb = f.stat().st_size / 1024
        log.info(f"  {f.name:<40} {size_kb:>8.1f} KB")
    log.info("═══════════════════════════════════════════")
    log.info("")
    log.info("BLENDERGIS IMPORT STEPS:")
    log.info("  1. Open Blender → BlenderGIS panel")
    log.info("  2. Set Scene CRS: EPSG:25833 (ETRS89 / UTM 33N)")
    log.info("  3. GIS > Import > GIS file → berlin_buildings.gpkg")
    log.info("     ↳ Extrude field: height_m  |  Type: Polygon")
    log.info("  4. GIS > Import → berlin_roads.gpkg (Type: Line)")
    log.info("  5. GIS > Import → berlin_water.gpkg (Type: Polygon)")
    log.info("  6. GIS > Import → berlin_landuse.gpkg (Type: Polygon)")
    log.info("  7. Optional: Get DEM via BlenderGIS SRTM downloader")
    log.info("     using bbox from berlin_terrain_bbox.geojson")

    return results


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Berlin Open Data → BlenderGIS pipeline")
    parser.add_argument(
        "--area", default="mitte",
        help=f"Area preset or minx,miny,maxx,maxy. Presets: {list(AREA_PRESETS.keys())}"
    )
    parser.add_argument(
        "--source", default="osm", choices=["osm", "alkis", "atkis", "all"],
        help="Data source(s) to fetch"
    )
    args = parser.parse_args()
    run_pipeline(area=args.area, source=args.source)
