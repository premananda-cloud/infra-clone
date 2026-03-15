
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

Generated: 2026-03-15 16:50:53.454885
