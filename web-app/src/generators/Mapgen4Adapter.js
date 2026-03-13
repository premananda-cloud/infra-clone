// Your extracted data from Step 1 (load as JSON)
import cityData from './city_buildings_with_embeddings.json';

// Mapgen4's core algorithms (adapted from their open-source code)
class UrbanGenerator {
    constructor(embeddingData) {
        this.data = embeddingData;
        this.clusterProfiles = this.analyzeClusters();
    }
    
    analyzeClusters() {
        // Group buildings by their embedding similarity
        const clusters = {};
        this.data.forEach(building => {
            const clusterId = this.getClusterId(building.embedding);
            if (!clusters[clusterId]) {
                clusters[clusterId] = [];
            }
            clusters[clusterId].push(building);
        });
        return clusters;
    }
    
    getClusterId(embedding) {
        // Use the KMeans model from Python to classify
        // You'll need to export the model or implement simple distance-based
        return this.predictCluster(embedding);
    }
    
    generateDistrict(centerX, centerY, clusterId) {
        const profile = this.clusterProfiles[clusterId];
        
        // Use Mapgen4's Voronoi diagram for street network
        const sites = this.generateStreetSites(centerX, centerY, profile.density);
        const diagram = this.computeVoronoi(sites);
        
        // Generate buildings based on real data patterns
        const buildings = [];
        profile.buildings.forEach(template => {
            // Procedurally generate variations of real building types
            const newBuilding = {
                position: this.findParcelLocation(diagram),
                height: template.avg_height * (0.8 + 0.4 * Math.random()),
                style: template.building_type,
                footprint: this.generateFootprint(template.footprint_pattern)
            };
            buildings.push(newBuilding);
        });
        
        return { diagram, buildings };
    }
    
    // Mapgen4's core algorithms
    computeVoronoi(sites) {
        // Mapgen4 uses Delaunay triangulation for terrain
        // We adapt it for street networks
        const delaunay = d3.Delaunay.from(sites);
        return delaunay.voronoi([0, 0, 1000, 1000]);
    }
    
    generateStreetSites(cx, cy, density) {
        // Use Poisson disc sampling (as in Mapgen4) for realistic street spacing
        const sites = [];
        const radius = 50 / Math.sqrt(density);
        
        // Mapgen4's grid-based optimization
        const gridSize = radius / Math.sqrt(2);
        const grid = {};
        
        // Generate with minimum distance constraint
        for (let i = 0; i < density * 10; i++) {
            const angle = Math.random() * 2 * Math.PI;
            const dist = Math.random() * 500;
            const x = cx + dist * Math.cos(angle);
            const y = cy + dist * Math.sin(angle);
            
            // Check grid constraints
            const gx = Math.floor(x / gridSize);
            const gy = Math.floor(y / gridSize);
            const key = `${gx},${gy}`;
            
            if (!grid[key]) {
                sites.push([x, y]);
                grid[key] = true;
            }
        }
        
        return sites;
    }
}
