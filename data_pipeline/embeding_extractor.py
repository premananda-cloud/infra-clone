import ee
import geopandas as gpd
import pandas as pd
import numpy as np

# Initialize Earth Engine
ee.Initialize()

# 1. Load AlphaEarth embeddings (annual composite)
embeddings = ee.ImageCollection("GOOGLE/SATELLITE_EMBEDDING/V1/ANNUAL") \
    .filterDate('2024-01-01', '2024-12-31') \
    .mosaic()

# 2. Define your study area (e.g., your city center)
geometry = ee.Geometry.Rectangle([-122.45, 37.75, -122.35, 37.82])  # San Francisco example

# 3. Extract building footprints from OpenStreetMap (free)
# First, get OSM data (you can download from Geofabrik or use osmnx)
import osmnx as ox
buildings = ox.geometries_from_bbox(37.82, -122.35, 37.75, -122.45, 
                                     tags={'building': True})

# 4. For each building, extract its embedding
building_embeddings = []

for idx, building in buildings.iterrows():
    # Get building centroid
    centroid = building.geometry.centroid
    point = ee.Geometry.Point([centroid.x, centroid.y])
    
    # Extract embedding for this location (100m buffer to capture context)
    embedding = embeddings.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=point.buffer(100),
        scale=10
    ).getInfo()
    
    # Store with building attributes
    building_embeddings.append({
        'geometry': building.geometry,
        'building_type': building.get('building', 'unknown'),
        'height': building.get('height', np.nan),
        'embedding': list(embedding.values())  # 64-dimensional vector
    })

# 5. Convert to GeoDataFrame and save
gdf = gpd.GeoDataFrame(building_embeddings)
gdf.to_file('city_buildings_with_embeddings.gpkg', driver='GPKG')