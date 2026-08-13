import geopandas as gpd
from pathlib import Path

# Find all GPKG files
for gpkg_file in Path(".").glob("*.gpkg"):
    print(f"Converting: {gpkg_file}")
    
    # Read the GPKG
    gdf = gpd.read_file(gpkg_file)
    
    # Create output name (change extension to .shp)
    shp_name = gpkg_file.stem + ".shp"
    
    # Save as Shapefile
    gdf.to_file(shp_name, driver="ESRI Shapefile")
    print(f"  → Saved: {shp_name}")

print("Done! All files converted to SHP format.")