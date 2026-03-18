"""
Berlin PBF → GeoPackage extractor (Geofabrik fallback)
=======================================================
For when Overpass is slow or you need the full city at once.

Download manually first:
  wget https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf

Then run:
  python berlin_pbf_extractor.py --pbf berlin-latest.osm.pbf --area mitte

Requires: osmium (osmium-tool) + geopandas
  sudo apt install osmium-tool     # Linux
  brew install osmium-tool         # macOS
"""

import subprocess, json, tempfile, os, sys, argparse, logging
from pathlib import Path
import geopandas as gpd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = Path("./output")
OUTPUT_DIR.mkdir(exist_ok=True)

TARGET_CRS = "EPSG:25833"

AREA_PRESETS = {
    "mitte":        (13.3600, 52.5050, 13.4200, 52.5350),
    "prenzlauer":   (13.4100, 52.5250, 13.4600, 52.5500),
    "kreuzberg":    (13.3850, 52.4850, 13.4350, 52.5100),
    "tiergarten":   (13.3300, 52.5050, 13.3800, 52.5200),
    "full_city":    (13.0900, 52.3400, 13.7600, 52.6800),
}

LAYER_FILTERS = {
    "buildings": "w/building",
    "roads":     "w/highway",
    "water":     "w/natural=water w/waterway",
    "landuse":   "w/landuse w/leisure=park",
}


def check_osmium():
    """Make sure osmium-tool is installed."""
    try:
        result = subprocess.run(["osmium", "version"], capture_output=True, text=True)
        log.info(f"osmium version: {result.stdout.strip()}")
        return True
    except FileNotFoundError:
        log.error("osmium-tool not found. Install with: sudo apt install osmium-tool")
        return False


def extract_bbox(pbf_path, bbox, output_path):
    """Use osmium to extract a bounding box from a PBF."""
    minx, miny, maxx, maxy = bbox
    cmd = [
        "osmium", "extract",
        "--bbox", f"{minx},{miny},{maxx},{maxy}",
        "--strategy", "complete-ways",
        "--output", str(output_path),
        "--overwrite",
        str(pbf_path)
    ]
    log.info(f"Extracting bbox from PBF: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"osmium extract failed: {result.stderr}")


def pbf_to_geojson(pbf_path, filter_expr, output_geojson):
    """
    Use osmium tags-filter to extract a layer, then export to GeoJSON.
    filter_expr examples: "w/building", "w/highway"
    """
    # Filter to a temp PBF
    filtered_pbf = str(output_geojson).replace(".geojson", "_filtered.osm.pbf")
    cmd_filter = [
        "osmium", "tags-filter",
        str(pbf_path),
        filter_expr,
        "--output", filtered_pbf,
        "--overwrite"
    ]
    result = subprocess.run(cmd_filter, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning(f"Filter failed for '{filter_expr}': {result.stderr}")
        return False

    # Export to GeoJSON
    cmd_export = [
        "osmium", "export",
        filtered_pbf,
        "--output", str(output_geojson),
        "--output-format", "geojson",
        "--overwrite"
    ]
    result = subprocess.run(cmd_export, capture_output=True, text=True)
    if result.returncode != 0:
        log.warning(f"Export failed: {result.stderr}")
        return False

    # Cleanup temp file
    try:
        os.remove(filtered_pbf)
    except OSError:
        pass

    return True


def process_buildings_geojson(geojson_path):
    """Load building GeoJSON and normalize height fields."""
    gdf = gpd.read_file(geojson_path)
    gdf = gdf[gdf.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()

    def parse_height(row):
        for col in ["height", "building:height"]:
            if col in row and pd.notna(row[col]):
                try:
                    return float(str(row[col]).replace("m", ""))
                except:
                    pass
        for col in ["building:levels", "levels"]:
            if col in row and pd.notna(row[col]):
                try:
                    return float(row[col]) * 3.0
                except:
                    pass
        return 9.0

    import pandas as pd
    gdf["height_m"] = gdf.apply(parse_height, axis=1)
    gdf["building_type"] = gdf.get("building", "yes")
    return gdf


def run_pbf_pipeline(pbf_path, area="mitte"):
    if not check_osmium():
        sys.exit(1)

    bbox = AREA_PRESETS.get(area)
    if not bbox:
        raise ValueError(f"Unknown area. Choose from: {list(AREA_PRESETS.keys())}")

    # Step 1: Clip PBF to bbox
    clipped_pbf = OUTPUT_DIR / f"berlin_{area}_clipped.osm.pbf"
    extract_bbox(pbf_path, bbox, clipped_pbf)
    log.info(f"Clipped PBF: {clipped_pbf}")

    # Step 2: Extract each layer
    import pandas as pd
    for layer_name, filter_expr in LAYER_FILTERS.items():
        log.info(f"Processing layer: {layer_name}")
        geojson_out = OUTPUT_DIR / f"berlin_{layer_name}_raw.geojson"
        gpkg_out = OUTPUT_DIR / f"berlin_{layer_name}.gpkg"

        success = pbf_to_geojson(clipped_pbf, filter_expr, geojson_out)
        if not success:
            log.warning(f"Skipping {layer_name}")
            continue

        try:
            if layer_name == "buildings":
                gdf = process_buildings_geojson(geojson_out)
            else:
                gdf = gpd.read_file(geojson_out)

            if gdf.empty:
                log.warning(f"No features in {layer_name}")
                continue

            if gdf.crs is None:
                gdf = gdf.set_crs("EPSG:4326")
            gdf = gdf.to_crs(TARGET_CRS)
            gdf.to_file(str(gpkg_out), driver="GPKG")
            log.info(f"  ✓ {layer_name}: {len(gdf)} features → {gpkg_out.name}")

            # Cleanup raw geojson
            os.remove(geojson_out)
        except Exception as e:
            log.error(f"Failed to process {layer_name}: {e}")

    log.info("PBF extraction complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Berlin PBF → GeoPackage for BlenderGIS")
    parser.add_argument("--pbf", required=True, help="Path to berlin-latest.osm.pbf")
    parser.add_argument("--area", default="mitte", help="Area preset")
    args = parser.parse_args()
    run_pbf_pipeline(args.pbf, args.area)
