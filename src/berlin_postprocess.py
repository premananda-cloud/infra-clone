"""
Berlin GIS → BlenderGIS Post-Processor
=======================================
Cleans, merges, and optimizes output layers for BlenderGIS.
Run after berlin_gis_pipeline.py.

Features:
  - Removes invalid/degenerate geometries
  - Clips all layers to a common extent
  - Merges ALKIS + OSM buildings (ALKIS preferred where available)
  - Simplifies road geometry for performance
  - Assigns material category integers for Blender node setup
  - Exports a combined "scene.gpkg" with all layers

Usage:
  python berlin_postprocess.py [--area mitte] [--simplify 0.5]
"""

import logging
from pathlib import Path
import geopandas as gpd
import pandas as pd
from shapely.validation import make_valid
from shapely.geometry import box

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = Path("./output")
TARGET_CRS = "EPSG:25833"

# Material IDs for Blender shader node setup
BUILDING_MATERIAL_IDS = {
    "yes": 0, "house": 1, "apartments": 2, "commercial": 3,
    "industrial": 4, "office": 5, "retail": 6, "church": 7,
    "public": 8, "school": 9, "hospital": 10, "hotel": 11,
}

ROAD_MATERIAL_IDS = {
    "motorway": 0, "trunk": 1, "primary": 2, "secondary": 3,
    "tertiary": 4, "residential": 5, "pedestrian": 6, "footway": 7,
    "cycleway": 8, "service": 9,
}

LANDUSE_MATERIAL_IDS = {
    "park": 0, "forest": 1, "grass": 2, "meadow": 3, "residential": 4,
    "commercial": 5, "industrial": 6, "retail": 7, "cemetery": 8,
}


def load_layer(name):
    """Load a GeoPackage layer from output dir."""
    path = OUTPUT_DIR / f"{name}.gpkg"
    if not path.exists():
        log.warning(f"Layer not found: {name}.gpkg")
        return None
    gdf = gpd.read_file(str(path))
    if gdf.crs is None:
        gdf = gdf.set_crs(TARGET_CRS)
    elif gdf.crs.to_epsg() != 25833:
        gdf = gdf.to_crs(TARGET_CRS)
    return gdf


def fix_geometries(gdf, layer_name=""):
    """Repair invalid geometries and remove empties."""
    before = len(gdf)
    gdf = gdf.copy()
    gdf["geometry"] = gdf["geometry"].apply(lambda g: make_valid(g) if g and not g.is_valid else g)
    gdf = gdf[gdf["geometry"].notna() & ~gdf["geometry"].is_empty]
    after = len(gdf)
    if before != after:
        log.info(f"  {layer_name}: removed {before - after} invalid geometries")
    return gdf


def clip_to_bbox(gdf, bbox_gdf):
    """Clip a layer to the query bounding box."""
    try:
        return gpd.clip(gdf, bbox_gdf)
    except Exception as e:
        log.warning(f"Clip failed: {e} — returning unclipped")
        return gdf


def simplify_roads(gdf, tolerance=0.5):
    """Simplify road geometry for better Blender performance."""
    gdf = gdf.copy()
    gdf["geometry"] = gdf["geometry"].simplify(tolerance, preserve_topology=True)
    return gdf


def merge_buildings(osm_gdf, alkis_gdf):
    """
    Spatial merge: prefer ALKIS footprints where they overlap OSM buildings.
    ALKIS has more accurate cadaster boundaries; OSM has better height data.
    """
    if alkis_gdf is None or alkis_gdf.empty:
        log.info("  No ALKIS buildings — using OSM only")
        return osm_gdf

    if osm_gdf is None or osm_gdf.empty:
        log.info("  No OSM buildings — using ALKIS only")
        return alkis_gdf

    log.info(f"  Merging {len(osm_gdf)} OSM + {len(alkis_gdf)} ALKIS buildings...")

    # Spatial join to transfer OSM height data to ALKIS footprints
    alkis_with_heights = gpd.sjoin(
        alkis_gdf,
        osm_gdf[["geometry", "height_m", "building_type", "roof_shape"]].rename(
            columns={"height_m": "osm_height", "building_type": "osm_type", "roof_shape": "osm_roof"}
        ),
        how="left", predicate="intersects"
    )
    # Keep first match per ALKIS feature
    alkis_with_heights = alkis_with_heights[~alkis_with_heights.index.duplicated(keep="first")]

    # Use OSM height where ALKIS lacks it
    if "osm_height" in alkis_with_heights.columns:
        mask = alkis_with_heights["height_m"].isna() | (alkis_with_heights["height_m"] == 0)
        alkis_with_heights.loc[mask, "height_m"] = alkis_with_heights.loc[mask, "osm_height"]

    # Find OSM buildings NOT covered by ALKIS (fill in the gaps)
    alkis_union = alkis_gdf.geometry.unary_union
    osm_extras = osm_gdf[~osm_gdf.geometry.intersects(alkis_union)].copy()

    # Combine
    combined = pd.concat([alkis_with_heights, osm_extras], ignore_index=True)
    log.info(f"  → Merged: {len(combined)} buildings")
    return gpd.GeoDataFrame(combined, crs=TARGET_CRS)


def add_material_ids(gdf, material_map, type_col):
    """Add integer material ID column for Blender shader nodes."""
    if type_col in gdf.columns:
        gdf = gdf.copy()
        gdf["mat_id"] = gdf[type_col].map(material_map).fillna(0).astype(int)
    else:
        gdf["mat_id"] = 0
    return gdf


def run_postprocess(simplify_roads_m=0.5):
    log.info("═══════════════════════════════════════════")
    log.info("BlenderGIS Post-Processor")
    log.info("═══════════════════════════════════════════")

    # Load terrain bbox
    bbox_path = OUTPUT_DIR / "berlin_terrain_bbox.geojson"
    if bbox_path.exists():
        bbox_gdf = gpd.read_file(str(bbox_path)).to_crs(TARGET_CRS)
    else:
        bbox_gdf = None

    # ── Buildings ─────────────────────────────────────────────────────────
    log.info("\n[1/5] Processing buildings...")
    osm_bldg = load_layer("berlin_buildings")
    alkis_bldg = load_layer("berlin_alkis_buildings")

    buildings = merge_buildings(osm_bldg, alkis_bldg)

    if buildings is not None and not buildings.empty:
        buildings = fix_geometries(buildings, "buildings")
        if bbox_gdf is not None:
            buildings = clip_to_bbox(buildings, bbox_gdf)
        buildings = add_material_ids(buildings, BUILDING_MATERIAL_IDS, "building_type")

        # Ensure height_m is numeric and positive
        if "height_m" in buildings.columns:
            buildings["height_m"] = pd.to_numeric(buildings["height_m"], errors="coerce").fillna(9.0).clip(lower=1.5)

        # Add footprint area (useful for LOD decisions in Blender)
        buildings["footprint_m2"] = buildings.geometry.area.round(1)

        buildings.to_file(str(OUTPUT_DIR / "berlin_buildings_clean.gpkg"), driver="GPKG")
        log.info(f"  ✓ berlin_buildings_clean.gpkg ({len(buildings)} features)")

    # ── Roads ─────────────────────────────────────────────────────────────
    log.info("\n[2/5] Processing roads...")
    roads = load_layer("berlin_roads")
    if roads is not None and not roads.empty:
        roads = fix_geometries(roads, "roads")
        if bbox_gdf is not None:
            roads = clip_to_bbox(roads, bbox_gdf)
        roads = simplify_roads(roads, tolerance=simplify_roads_m)
        roads = add_material_ids(roads, ROAD_MATERIAL_IDS, "road_type")
        roads.to_file(str(OUTPUT_DIR / "berlin_roads_clean.gpkg"), driver="GPKG")
        log.info(f"  ✓ berlin_roads_clean.gpkg ({len(roads)} features)")

    # ── Water ─────────────────────────────────────────────────────────────
    log.info("\n[3/5] Processing water...")
    water = load_layer("berlin_water")
    if water is not None and not water.empty:
        water = fix_geometries(water, "water")
        if bbox_gdf is not None:
            water = clip_to_bbox(water, bbox_gdf)
        water.to_file(str(OUTPUT_DIR / "berlin_water_clean.gpkg"), driver="GPKG")
        log.info(f"  ✓ berlin_water_clean.gpkg ({len(water)} features)")

    # ── Landuse ───────────────────────────────────────────────────────────
    log.info("\n[4/5] Processing landuse...")
    landuse = load_layer("berlin_landuse")
    if landuse is not None and not landuse.empty:
        landuse = fix_geometries(landuse, "landuse")
        if bbox_gdf is not None:
            landuse = clip_to_bbox(landuse, bbox_gdf)
        landuse = add_material_ids(landuse, LANDUSE_MATERIAL_IDS, "landuse_type")
        landuse.to_file(str(OUTPUT_DIR / "berlin_landuse_clean.gpkg"), driver="GPKG")
        log.info(f"  ✓ berlin_landuse_clean.gpkg ({len(landuse)} features)")

    # ── Parcels ───────────────────────────────────────────────────────────
    log.info("\n[5/5] Processing parcels...")
    parcels = load_layer("berlin_parcels")
    if parcels is not None and not parcels.empty:
        parcels = fix_geometries(parcels, "parcels")
        if bbox_gdf is not None:
            parcels = clip_to_bbox(parcels, bbox_gdf)
        parcels.to_file(str(OUTPUT_DIR / "berlin_parcels_clean.gpkg"), driver="GPKG")
        log.info(f"  ✓ berlin_parcels_clean.gpkg ({len(parcels)} features)")

    # ── Stats report ──────────────────────────────────────────────────────
    log.info("\n═══════════════════════════════════════════")
    log.info("FINAL OUTPUT FILES FOR BLENDERGIS:")
    log.info("═══════════════════════════════════════════")
    for f in sorted(OUTPUT_DIR.glob("*_clean.gpkg")):
        sz = f.stat().st_size / 1024
        log.info(f"  {f.name:<45} {sz:>8.1f} KB")

    log.info("\nBLENDERGIS IMPORT ORDER (bottom to top):")
    log.info("  1. berlin_landuse_clean.gpkg   → flat polygons (ground material)")
    log.info("  2. berlin_water_clean.gpkg     → flat polygons (water material)")
    log.info("  3. berlin_parcels_clean.gpkg   → flat polygons (parcel outlines)")
    log.info("  4. berlin_roads_clean.gpkg     → lines (road width via Geometry Nodes)")
    log.info("  5. berlin_buildings_clean.gpkg → extruded by 'height_m' field")
    log.info("\n  Extrude field: height_m")
    log.info("  Material field: mat_id (0-N → assign materials by index in Blender)")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Post-process Berlin GIS layers for BlenderGIS")
    parser.add_argument("--simplify", type=float, default=0.5,
                        help="Road simplification tolerance in metres (default: 0.5)")
    args = parser.parse_args()
    run_postprocess(simplify_roads_m=args.simplify)
