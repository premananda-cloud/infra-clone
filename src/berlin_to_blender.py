"""
Berlin GPKG → SHP + TIF Converter for BlenderGIS
==================================================
Converts existing *_clean.gpkg files into:

  shp/
    berlin_buildings.shp       ← building footprints (with height_m, mat_id)
    berlin_roads.shp           ← road network
    berlin_water.shp           ← water bodies
    berlin_landuse.shp         ← land use polygons
    berlin_parcels.shp         ← cadaster parcels

  tif/
    berlin_building_height.tif ← height_m field burned to raster (LOD1 DSM)
    berlin_ground_mask.tif     ← binary land/no-land mask
    berlin_landuse_class.tif   ← landuse mat_id burned to raster
    berlin_roads_mask.tif      ← road presence raster

All original .gpkg files are kept untouched.

Usage:
  python berlin_to_blender.py [--input ./output] [--res 1.0] [--no-tif] [--no-shp]

Options:
  --input   Directory containing *_clean.gpkg files  (default: ./output)
  --res     GeoTIFF pixel size in metres              (default: 1.0m)
  --no-tif  Skip raster outputs
  --no-shp  Skip shapefile outputs

Requirements:
  pip install geopandas rasterio fiona shapely pyproj
"""

import argparse, logging, warnings
from pathlib import Path

import numpy as np
import geopandas as gpd
import rasterio
from rasterio.transform import from_bounds
from rasterio.features import rasterize
from rasterio.crs import CRS
from shapely.geometry import mapping, box

warnings.filterwarnings("ignore", category=RuntimeWarning)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

TARGET_CRS   = "EPSG:25833"
TARGET_EPSG  = 25833


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def load_gpkg(input_dir: Path, stem: str) -> gpd.GeoDataFrame | None:
    """Load a *_clean.gpkg or fallback to non-clean version."""
    for name in (f"{stem}_clean.gpkg", f"{stem}.gpkg"):
        p = input_dir / name
        if p.exists():
            gdf = gpd.read_file(str(p))
            if gdf.crs is None:
                gdf = gdf.set_crs(TARGET_CRS)
            elif gdf.crs.to_epsg() != TARGET_EPSG:
                gdf = gdf.to_crs(TARGET_CRS)
            log.info(f"  loaded {name}  ({len(gdf)} features)")
            return gdf
    log.warning(f"  {stem}: no .gpkg found — skipping")
    return None


def get_scene_bounds(gdfs: list) -> tuple:
    """Compute merged bounding box from a list of GeoDataFrames."""
    all_bounds = [gdf.total_bounds for gdf in gdfs if gdf is not None and not gdf.empty]
    if not all_bounds:
        raise ValueError("No valid layers to compute bounds from")
    arr = np.array(all_bounds)
    return float(arr[:,0].min()), float(arr[:,1].min()), float(arr[:,2].max()), float(arr[:,3].max())


def safe_shp_col(name: str) -> str:
    """Shapefile column names max 10 chars."""
    return name[:10]


def write_shp(gdf: gpd.GeoDataFrame, out_path: Path):
    """Write GeoDataFrame to Shapefile, sanitising column names."""
    gdf = gdf.copy()
    # Rename columns > 10 chars
    rename = {c: safe_shp_col(c) for c in gdf.columns if c != "geometry" and len(c) > 10}
    if rename:
        gdf = gdf.rename(columns=rename)
        log.info(f"    ↳ truncated columns: {rename}")
    # Drop list/dict columns (unsupported in SHP)
    for col in list(gdf.columns):
        if col == "geometry":
            continue
        if gdf[col].apply(lambda x: isinstance(x, (list, dict))).any():
            gdf = gdf.drop(columns=[col])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(str(out_path), driver="ESRI Shapefile")
    log.info(f"  ✓ {out_path.name}  ({len(gdf)} features)")


# ─────────────────────────────────────────────────────────────────────────────
# VECTOR → SHP
# ─────────────────────────────────────────────────────────────────────────────

def export_shapefiles(layers: dict, shp_dir: Path):
    log.info("\n[SHP] Exporting shapefiles...")
    shp_dir.mkdir(parents=True, exist_ok=True)

    # ── Buildings ────────────────────────────────────────────────────────
    bldg = layers.get("buildings")
    if bldg is not None and not bldg.empty:
        # Keep only polygon geometries
        bldg = bldg[bldg.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
        # Ensure essential columns exist
        for col, default in [("height_m", 9.0), ("mat_id", 0), ("bldg_type", "yes")]:
            shp_col = safe_shp_col(col)
            src = col if col in bldg.columns else ("building_type" if col == "bldg_type" else None)
            if src and src in bldg.columns:
                bldg[shp_col] = bldg[src]
            elif shp_col not in bldg.columns:
                bldg[shp_col] = default
        keep = ["geometry", "height_m", "mat_id", "bldg_type",
                "min_height", "roof_shape", "name", "addr_stre", "addr_hous"]
        keep = [c for c in keep if c in bldg.columns]
        write_shp(bldg[keep], shp_dir / "berlin_buildings.shp")

    # ── Roads ────────────────────────────────────────────────────────────
    roads = layers.get("roads")
    if roads is not None and not roads.empty:
        roads = roads[roads.geometry.type.isin(["LineString", "MultiLineString"])].copy()
        keep = ["geometry", "road_type", "road_name", "lanes", "surface", "mat_id"]
        keep = [c for c in keep if c in roads.columns]
        write_shp(roads[keep], shp_dir / "berlin_roads.shp")

    # ── Water ────────────────────────────────────────────────────────────
    water = layers.get("water")
    if water is not None and not water.empty:
        water = water[water.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
        keep = ["geometry", "water_type", "water_name", "mat_id"]
        keep = [c for c in keep if c in water.columns]
        write_shp(water[keep], shp_dir / "berlin_water.shp")

    # ── Landuse ──────────────────────────────────────────────────────────
    landuse = layers.get("landuse")
    if landuse is not None and not landuse.empty:
        landuse = landuse[landuse.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
        keep = ["geometry", "landuse_ty", "area_name", "mat_id"]
        keep_src = ["geometry", "landuse_type", "area_name", "mat_id"]
        # rename landuse_type → landuse_ty for shp
        if "landuse_type" in landuse.columns:
            landuse = landuse.rename(columns={"landuse_type": "landuse_ty"})
        keep = [c for c in ["geometry", "landuse_ty", "area_name", "mat_id"] if c in landuse.columns]
        write_shp(landuse[keep], shp_dir / "berlin_landuse.shp")

    # ── Parcels ──────────────────────────────────────────────────────────
    parcels = layers.get("parcels")
    if parcels is not None and not parcels.empty:
        parcels = parcels[parcels.geometry.type.isin(["Polygon", "MultiPolygon"])].copy()
        write_shp(parcels, shp_dir / "berlin_parcels.shp")


# ─────────────────────────────────────────────────────────────────────────────
# VECTOR → RASTER (GeoTIFF)
# ─────────────────────────────────────────────────────────────────────────────

def make_transform_shape(minx, miny, maxx, maxy, res):
    """Compute rasterio transform and output shape for a bbox + resolution."""
    width  = max(1, int(np.ceil((maxx - minx) / res)))
    height = max(1, int(np.ceil((maxy - miny) / res)))
    transform = from_bounds(minx, miny, maxx, maxy, width, height)
    return transform, (height, width)


def burn_to_tif(gdf, value_col, bounds, res, out_path, dtype="float32",
                background=0.0, all_touched=False):
    """
    Rasterize a GeoDataFrame column into a GeoTIFF.

    gdf        : GeoDataFrame (polygon or line)
    value_col  : column to burn as pixel value (or None for binary mask)
    bounds     : (minx, miny, maxx, maxy) in TARGET_CRS
    res        : pixel size in metres
    out_path   : output .tif path
    """
    minx, miny, maxx, maxy = bounds
    transform, shape = make_transform_shape(minx, miny, maxx, maxy, res)

    if gdf is None or gdf.empty:
        log.warning(f"  {out_path.name}: empty layer — writing blank raster")
        arr = np.full(shape, background, dtype=dtype)
        _write_tif(arr, transform, out_path, dtype)
        return

    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty].copy()

    if value_col and value_col in gdf.columns:
        import pandas as pd
        gdf[value_col] = pd.to_numeric(gdf[value_col], errors="coerce").fillna(background)
        shapes = [(mapping(row.geometry), float(row[value_col])) for _, row in gdf.iterrows()]
    else:
        # Binary mask
        shapes = [(mapping(geom), 1.0) for geom in gdf.geometry]

    if not shapes:
        arr = np.full(shape, background, dtype=dtype)
    else:
        arr = rasterize(
            shapes,
            out_shape=shape,
            transform=transform,
            fill=background,
            dtype=dtype,
            all_touched=all_touched,
        )

    _write_tif(arr, transform, out_path, dtype)
    log.info(f"  ✓ {out_path.name}  "
             f"({shape[1]}×{shape[0]}px  "
             f"res={res}m  "
             f"min={arr.min():.1f} max={arr.max():.1f})")


def _write_tif(arr, transform, out_path, dtype):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        str(out_path), "w",
        driver="GTiff",
        height=arr.shape[0],
        width=arr.shape[1],
        count=1,
        dtype=dtype,
        crs=CRS.from_epsg(TARGET_EPSG),
        transform=transform,
        compress="lzw",          # lossless, keeps file small
        nodata=0,
    ) as dst:
        dst.write(arr, 1)


def export_geotiffs(layers: dict, tif_dir: Path, res: float):
    log.info(f"\n[TIF] Exporting GeoTIFFs at {res}m resolution...")
    tif_dir.mkdir(parents=True, exist_ok=True)

    # Compute scene bounds from all layers
    valid = [v for v in layers.values() if v is not None and not v.empty]
    if not valid:
        log.error("No valid layers — cannot compute bounds for rasterization")
        return

    bounds = get_scene_bounds(valid)
    log.info(f"  Scene bounds (ETRS89/UTM33N): {[round(b,1) for b in bounds]}")
    w = (bounds[2] - bounds[0]) / 1000
    h = (bounds[3] - bounds[1]) / 1000
    log.info(f"  Scene size: {w:.2f} km × {h:.2f} km")

    # ── Building height DSM ───────────────────────────────────────────────
    bldg = layers.get("buildings")
    burn_to_tif(
        bldg, "height_m", bounds, res,
        tif_dir / "berlin_building_height.tif",
        dtype="float32", background=0.0,
    )

    # ── Building footprint mask (binary) ─────────────────────────────────
    burn_to_tif(
        bldg, None, bounds, res,
        tif_dir / "berlin_building_mask.tif",
        dtype="uint8", background=0,
    )

    # ── Road mask ────────────────────────────────────────────────────────
    roads = layers.get("roads")
    burn_to_tif(
        roads, None, bounds, res,
        tif_dir / "berlin_roads_mask.tif",
        dtype="uint8", background=0, all_touched=True,
    )

    # ── Water mask ───────────────────────────────────────────────────────
    water = layers.get("water")
    burn_to_tif(
        water, None, bounds, res,
        tif_dir / "berlin_water_mask.tif",
        dtype="uint8", background=0,
    )

    # ── Landuse class raster ─────────────────────────────────────────────
    landuse = layers.get("landuse")
    # Ensure mat_id exists
    if landuse is not None and "mat_id" not in landuse.columns:
        landuse = landuse.copy()
        landuse["mat_id"] = 0
    burn_to_tif(
        landuse, "mat_id", bounds, res,
        tif_dir / "berlin_landuse_class.tif",
        dtype="uint8", background=255,   # 255 = no landuse
    )

    # ── Combined ground mask (everything = 1) ────────────────────────────
    all_polys = []
    for key in ("buildings", "water", "landuse", "parcels"):
        lyr = layers.get(key)
        if lyr is not None and not lyr.empty:
            poly = lyr[lyr.geometry.type.isin(["Polygon","MultiPolygon"])]
            if not poly.empty:
                all_polys.append(poly[["geometry"]])
    if all_polys:
        import pandas as pd
        combined = gpd.GeoDataFrame(
            pd.concat(all_polys, ignore_index=True), crs=TARGET_CRS
        )
        burn_to_tif(
            combined, None, bounds, res,
            tif_dir / "berlin_ground_mask.tif",
            dtype="uint8", background=0,
        )


# ─────────────────────────────────────────────────────────────────────────────
# BLENDERGIS GUIDE FILE
# ─────────────────────────────────────────────────────────────────────────────

def write_blendergis_guide(out_dir: Path, shp_dir: Path, tif_dir: Path, res: float):
    guide = {
        "crs": "EPSG:25833",
        "crs_name": "ETRS89 / UTM zone 33N",
        "pixel_resolution_m": res,
        "import_order": [
            "1. GIS > Set scene CRS → EPSG:25833",
            "2. Import berlin_landuse.shp     (Polygon, flat ground)",
            "3. Import berlin_water.shp       (Polygon, flat)",
            "4. Import berlin_parcels.shp     (Polygon, flat outlines)",
            "5. Import berlin_roads.shp       (Line)",
            "6. Import berlin_buildings.shp   (Polygon, Extrude field: height_m)",
        ],
        "tif_usage": {
            "berlin_building_height.tif": "Use as displacement texture OR import as terrain mesh for LOD1 city model",
            "berlin_building_mask.tif":   "Binary mask for footprint-based material selection",
            "berlin_roads_mask.tif":      "Road presence for procedural road texturing",
            "berlin_water_mask.tif":      "Water mask for shader blend node",
            "berlin_landuse_class.tif":   "Integer class raster (0-8) → ColorRamp → material",
            "berlin_ground_mask.tif":     "All-features mask for ground plane trimming",
        },
        "blender_tips": [
            "Building height_m field → use as Extrude value in BlenderGIS import dialog",
            "mat_id field (int) → Attribute node → Color Ramp → assign materials by index",
            "For realistic scale: 1 Blender unit = 1 metre (BlenderGIS sets this automatically with EPSG:25833)",
            "berlin_building_height.tif can be used as a Displacement modifier on a grid mesh",
            "Combine building_height.tif + building_mask.tif in a MixShader for rooftop vs wall",
        ],
        "files": {
            "shp": [str(p.name) for p in sorted(shp_dir.glob("*.shp"))] if shp_dir.exists() else [],
            "tif": [str(p.name) for p in sorted(tif_dir.glob("*.tif"))] if tif_dir.exists() else [],
        }
    }

    import json
    out_path = out_dir / "blendergis_import_guide.json"
    with open(out_path, "w") as f:
        json.dump(guide, f, indent=2)
    log.info(f"\n  ✓ Import guide → {out_path.name}")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def run(input_dir: Path, res: float, do_shp: bool, do_tif: bool):
    log.info("═══════════════════════════════════════════════════")
    log.info("Berlin GPKG → SHP + TIF Converter (BlenderGIS)")
    log.info(f"  Input  : {input_dir.resolve()}")
    log.info(f"  Res    : {res}m/px")
    log.info(f"  Outputs: SHP={'yes' if do_shp else 'no'}  TIF={'yes' if do_tif else 'no'}")
    log.info("═══════════════════════════════════════════════════")

    shp_dir = input_dir / "shp"
    tif_dir = input_dir / "tif"

    # Load all available layers
    log.info("\n[LOAD] Reading GeoPackage layers...")
    layers = {
        "buildings": load_gpkg(input_dir, "berlin_buildings"),
        "roads":     load_gpkg(input_dir, "berlin_roads"),
        "water":     load_gpkg(input_dir, "berlin_water"),
        "landuse":   load_gpkg(input_dir, "berlin_landuse"),
        "parcels":   load_gpkg(input_dir, "berlin_parcels"),
    }

    loaded = sum(1 for v in layers.values() if v is not None and not v.empty)
    if loaded == 0:
        log.error("No layers loaded. Make sure *_clean.gpkg or *.gpkg files exist in the input directory.")
        return

    log.info(f"  {loaded}/5 layers loaded successfully")

    if do_shp:
        export_shapefiles(layers, shp_dir)

    if do_tif:
        export_geotiffs(layers, tif_dir, res)

    write_blendergis_guide(input_dir, shp_dir, tif_dir, res)

    # Final summary
    log.info("\n═══════════════════════════════════════════════════")
    log.info("OUTPUT:")
    for d, glob in [(shp_dir, "*.shp"), (tif_dir, "*.tif")]:
        if d.exists():
            for f in sorted(d.glob(glob)):
                kb = f.stat().st_size / 1024
                log.info(f"  {f.relative_to(input_dir)!s:<45} {kb:>8.1f} KB")
    log.info("═══════════════════════════════════════════════════")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Convert Berlin .gpkg layers → Shapefile + GeoTIFF for BlenderGIS"
    )
    parser.add_argument("--input",  default="./output",
                        help="Directory with *_clean.gpkg files (default: ./output)")
    parser.add_argument("--res",    type=float, default=1.0,
                        help="GeoTIFF pixel size in metres (default: 1.0)")
    parser.add_argument("--no-tif", action="store_true", help="Skip GeoTIFF output")
    parser.add_argument("--no-shp", action="store_true", help="Skip Shapefile output")
    args = parser.parse_args()

    run(
        input_dir=Path(args.input),
        res=args.res,
        do_shp=not args.no_shp,
        do_tif=not args.no_tif,
    )
