import geopandas as gpd
from shapely.geometry import Polygon, Point, LineString
import numpy as np
import pandas as pd
import os
from math import sin, cos, radians

# Create output directory
os.makedirs("blender_gis_output", exist_ok=True)

# Set coordinate system - Using a projected CRS suitable for local area (meters)
# UTM zone 33N (common for Europe) - adjust based on your location
local_crs = "EPSG:32633"  # UTM zone 33N

# ============================================
# CREATE BUILDINGS (3D extrusion in BlenderGIS)
# ============================================
buildings = []
building_heights = []
building_types = []
building_names = []

# Create a more interesting building layout
building_positions = [
    # Office buildings (taller)
    (10, 10, 25, "Office_A"), (40, 10, 30, "Office_B"), (70, 10, 28, "Office_C"),
    (10, 40, 35, "Tower_A"), (70, 40, 40, "Tower_B"),
    
    # Residential buildings (medium height)
    (25, 25, 15, "Residential_A"), (55, 25, 18, "Residential_B"),
    (25, 55, 12, "Residential_C"), (55, 55, 16, "Residential_D"),
    
    # Small shops/commercial (lower height)
    (10, 70, 8, "Shop_A"), (40, 70, 10, "Shop_B"), (70, 70, 8, "Shop_C"),
    
    # Unique buildings
    (45, 45, 22, "Town_Hall"), (30, 80, 20, "School"),
]

for x, y, height, name in building_positions:
    # Create rectangular buildings with slight variations
    width = np.random.randint(8, 15)
    depth = np.random.randint(8, 15)
    
    # Some buildings have L-shape for variety
    if "Tower" in name or "Hall" in name:
        # L-shaped building
        buildings.append(Polygon([
            (x, y),
            (x + width, y),
            (x + width, y + depth//2),
            (x + width//2, y + depth//2),
            (x + width//2, y + depth),
            (x, y + depth)
        ]))
    else:
        # Rectangle building
        buildings.append(Polygon([
            (x, y),
            (x + width, y),
            (x + width, y + depth),
            (x, y + depth)
        ]))
    
    building_heights.append(height)
    building_types.append('commercial' if 'Office' in name or 'Shop' in name else 'residential')
    building_names.append(name)

# ============================================
# CREATE ROADS (as lines and polygons for different uses)
# ============================================
# Road centerlines (for network)
road_centerlines = [
    LineString([(0, 15), (100, 15)]),   # Main horizontal
    LineString([(0, 45), (100, 45)]),    # Secondary horizontal
    LineString([(0, 75), (100, 75)]),    # Tertiary horizontal
    LineString([(20, 0), (20, 100)]),    # Main vertical
    LineString([(50, 0), (50, 100)]),    # Secondary vertical
    LineString([(80, 0), (80, 100)]),    # Tertiary vertical
]

# Road polygons (for visualization)
road_polygons = []
road_widths = [12, 8, 6, 12, 8, 6]  # Widths corresponding to roads above
road_names = ['Main_St', 'Second_Ave', 'Third_St', 'Broadway', 'Park_Rd', 'Elm_St']

for line, width, name in zip(road_centerlines, road_widths, road_names):
    # Create road polygon by buffering the centerline
    road_poly = line.buffer(width/2, cap_style=2, join_style=2)
    road_polygons.append(road_poly)

# ============================================
# CREATE PARKS AND GREEN SPACES
# ============================================
parks = [
    # Central park with pond
    Polygon([
        (30, 30),
        (45, 28),
        (60, 32),
        (58, 48),
        (42, 52),
        (28, 45)
    ]),
    
    # Small plaza
    Polygon([
        (75, 75),
        (85, 73),
        (88, 83),
        (78, 88),
        (70, 82)
    ]),
    
    # Garden
    Polygon([
        (5, 85),
        (15, 83),
        (18, 93),
        (8, 95),
        (3, 90)
    ])
]

park_names = ['Central_Park', 'Plaza', 'Garden']
park_types = ['park', 'plaza', 'garden']

# ============================================
# CREATE TREES AND POINT FEATURES
# ============================================
trees = []
tree_species = []
tree_heights = []
tree_diameters = []

# Generate trees in a grid pattern within parks and along streets
for i in range(15):
    for j in range(15):
        x = i * 7 + 2
        y = j * 7 + 2
        
        # Place trees only in park areas or along streets
        in_park = False
        for park in parks:
            if park.contains(Point(x, y)):
                in_park = True
                break
        
        # Check if near roads
        near_road = False
        for road in road_polygons:
            if road.distance(Point(x, y)) < 3:
                near_road = True
                break
        
        if in_park or near_road:
            trees.append(Point(x, y))
            
            # Different species based on location
            if in_park:
                species = np.random.choice(['Oak', 'Maple', 'Elm', 'Pine'])
                height = np.random.randint(8, 15)
                diameter = np.random.uniform(0.3, 1.0)
            else:
                species = np.random.choice(['Linden', 'Plane', 'Chestnut'])
                height = np.random.randint(5, 10)
                diameter = np.random.uniform(0.2, 0.6)
            
            tree_species.append(species)
            tree_heights.append(height)
            tree_diameters.append(diameter)

# Add lamp posts along main streets
lamp_posts = []
for i in range(5, 95, 15):
    lamp_posts.append(Point(i, 15))
    lamp_posts.append(Point(i, 45))
    lamp_posts.append(Point(20, i))
    lamp_posts.append(Point(50, i))

# ============================================
# CREATE GEODATAFRAMES
# ============================================

# 1. BUILDINGS (Polygons with height attribute for extrusion)
gdf_buildings = gpd.GeoDataFrame(
    {
        'id': range(len(buildings)),
        'name': building_names,
        'type': building_types,
        'height': building_heights,
        'roof_type': np.random.choice(['flat', 'pitched', 'domed'], len(buildings)),
        'color': np.random.choice(['gray', 'brown', 'beige', 'white'], len(buildings)),
        'geometry': buildings
    },
    crs=local_crs
)

# 2. ROADS (Polygons for visualization)
gdf_roads = gpd.GeoDataFrame(
    {
        'id': range(len(road_polygons)),
        'name': road_names,
        'width': road_widths,
        'type': 'road',
        'surface': 'asphalt',
        'lanes': [4, 2, 2, 4, 2, 2],
        'geometry': road_polygons
    },
    crs=local_crs
)

# 3. PARKS (Polygons)
gdf_parks = gpd.GeoDataFrame(
    {
        'id': range(len(parks)),
        'name': park_names,
        'type': park_types,
        'maintenance': ['high', 'medium', 'medium'],
        'has_water': [True, False, False],
        'geometry': parks
    },
    crs=local_crs
)

# 4. TREES (Points with height) - FIXED field name to avoid shapefile limitation
gdf_trees = gpd.GeoDataFrame(
    {
        'id': range(len(trees)),
        'type': 'tree',
        'species': tree_species,
        'height': tree_heights,
        'crown_diam': tree_diameters,  # Changed from 'crown_diameter' to avoid field name truncation
        'age': np.random.randint(5, 50, len(trees)),
        'geometry': trees
    },
    crs=local_crs
)

# 5. LAMP POSTS (Points)
gdf_lamps = gpd.GeoDataFrame(
    {
        'id': range(len(lamp_posts)),
        'type': 'lamp_post',
        'height': 8,
        'light_type': 'LED',
        'power': 50,
        'geometry': lamp_posts
    },
    crs=local_crs
)

# ============================================
# SAVE ALL SHAPEFILES
# ============================================

# Save individual shapefiles
gdf_buildings.to_file("blender_gis_output/buildings.shp")
print("✅ Saved: buildings.shp ({} features)".format(len(gdf_buildings)))

gdf_roads.to_file("blender_gis_output/roads.shp")
print("✅ Saved: roads.shp ({} features)".format(len(gdf_roads)))

gdf_parks.to_file("blender_gis_output/parks.shp")
print("✅ Saved: parks.shp ({} features)".format(len(gdf_parks)))

gdf_trees.to_file("blender_gis_output/trees.shp")
print("✅ Saved: trees.shp ({} features)".format(len(gdf_trees)))

gdf_lamps.to_file("blender_gis_output/lamp_posts.shp")
print("✅ Saved: lamp_posts.shp ({} features)".format(len(gdf_lamps)))

# ============================================
# CREATE A COMBINED FILE (optional) - FIXED the column selection issue
# ============================================
# First, prepare each dataframe with consistent columns
buildings_for_combine = gdf_buildings[['id', 'name', 'type', 'geometry']].copy()
buildings_for_combine['height'] = gdf_buildings['height']  # Add height column
buildings_for_combine['layer'] = 'building'

roads_for_combine = gdf_roads[['id', 'name', 'type', 'geometry']].copy()
roads_for_combine['height'] = 0  # Add height column with default value
roads_for_combine['layer'] = 'road'

parks_for_combine = gdf_parks[['id', 'name', 'type', 'geometry']].copy()
parks_for_combine['height'] = 0  # Add height column with default value
parks_for_combine['layer'] = 'park'

# Combine all polygons
combined_polygons = pd.concat([
    buildings_for_combine,
    roads_for_combine,
    parks_for_combine
], ignore_index=True)

# Convert back to GeoDataFrame
combined_polygons = gpd.GeoDataFrame(combined_polygons, crs=local_crs, geometry='geometry')

# Save combined file
combined_polygons.to_file("blender_gis_output/city_polygons.shp")
print("✅ Saved: city_polygons.shp ({} features)".format(len(combined_polygons)))

# ============================================
# CREATE POINTS COMBINED FILE
# ============================================
combined_points = pd.concat([
    gdf_trees[['id', 'type', 'height', 'geometry']].assign(point_type='tree'),
    gdf_lamps[['id', 'type', 'height', 'geometry']].assign(point_type='lamp')
], ignore_index=True)

combined_points = gpd.GeoDataFrame(combined_points, crs=local_crs, geometry='geometry')
combined_points.to_file("blender_gis_output/city_points.shp")
print("✅ Saved: city_points.shp ({} features)".format(len(combined_points)))

# ============================================
# CREATE A README FILE WITH INSTRUCTIONS
# ============================================
readme_content = """
BLENDERGIS IMPORT INSTRUCTIONS
==============================

These shapefiles are prepared for BlenderGIS addon.

Coordinate System: UTM Zone 33N (EPSG:32633)

Files included:
- buildings.shp: Building footprints with height attribute for 3D extrusion
- roads.shp: Road polygons
- parks.shp: Green spaces
- trees.shp: Tree locations with height and species
- lamp_posts.shp: Street furniture
- city_polygons.shp: Combined polygon layer (buildings + roads + parks)
- city_points.shp: Combined point layer (trees + lamp posts)

HOW TO USE IN BLENDER:
1. Install BlenderGIS addon if not already installed
2. In Blender: File > Import > Shapefile (.shp)
3. Select any of the .shp files
4. For buildings: Use the height attribute to extrude (in BlenderGIS properties)
5. For trees: Use the height attribute for scaling

FIELD NAME NOTES:
- Shapefile field names are limited to 10 characters
- 'crown_diam' = crown diameter (original was truncated)
- 'light_type' = type of lamp

TIPS:
- All coordinates are in meters (UTM projection)
- Heights are in meters
- Import buildings first, then use "Extrude 3D" in BlenderGIS
- Trees can be replaced with 3D models using the point locations

Generated: {}
""".format(pd.Timestamp.now())

with open("blender_gis_output/README.txt", "w") as f:
    f.write(readme_content)

print("\n✅ Saved: README.txt with instructions")

# Print summary
print("\n" + "="*50)
print("DATASET SUMMARY FOR BLENDERGIS")
print("="*50)
print(f"Buildings:     {len(gdf_buildings):3d} features (with height attribute)")
print(f"Roads:         {len(gdf_roads):3d} features")
print(f"Parks:         {len(gdf_parks):3d} features")
print(f"Trees:         {len(gdf_trees):3d} features")
print(f"Lamp Posts:    {len(gdf_lamps):3d} features")
print(f"Combined Poly: {len(combined_polygons):3d} features")
print(f"Combined Points: {len(combined_points):3d} features")
print("="*50)
print("\n✅ All files saved to: 'blender_gis_output/'")
print("📁 Ready for BlenderGIS import!")