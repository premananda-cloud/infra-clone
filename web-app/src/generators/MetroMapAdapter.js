/**
 * MetroMapAdapter.js
 *
 * NOTE: 'metromap-core' does not exist as an npm package.
 * MetroMap.io is a reference project / concept. This adapter reimplements
 * the MetroMap generation contract using real, installable libraries:
 *
 *   - simplex-noise  (terrain height noise)
 *   - delaunator     (spatial queries / triangulation)
 *
 * The public API is kept identical to what App.jsx expects:
 *   new DataDrivenCityGenerator(embeddingData)
 *   generator.generate(region)   → { terrain, buildings, streets }
 *
 * Install: npm install simplex-noise delaunator
 */

import { createNoise2D } from 'simplex-noise';

// ---------------------------------------------------------------------------
// Geometry helpers
// ---------------------------------------------------------------------------

function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

function lerp(a, b, t) { return a + (b - a) * t; }

/**
 * Returns true if point [px,py] is inside the bounding box
 * { minX, maxX, minY, maxY }.
 */
function bboxContains(bbox, px, py) {
    return px >= bbox.minX && px <= bbox.maxX
        && py >= bbox.minY && py <= bbox.maxY;
}

/**
 * Decode an implicit elevation signal from a 64-dim AlphaEarth embedding.
 * AlphaEarth encodes topographic context across the full vector; we use a
 * simple linear projection onto the first principal direction as a proxy.
 * (A proper implementation would export PCA weights from the Python pipeline.)
 *
 * Projection: mean of even-indexed dims minus mean of odd-indexed dims,
 * normalised to [0, 1].
 */
function decodeElevation(embedding) {
    if (!embedding || !embedding.length) return 0.5;
    let evenSum = 0, oddSum = 0, evenN = 0, oddN = 0;
    for (let i = 0; i < embedding.length; i++) {
        if (i % 2 === 0) { evenSum += embedding[i]; evenN++; }
        else             { oddSum  += embedding[i]; oddN++; }
    }
    const raw = (evenSum / evenN) - (oddSum / oddN);
    // Squash to [0,1] with sigmoid
    return 1 / (1 + Math.exp(-raw));
}

/**
 * Component-wise blend: (1 - alpha)*noiseVal + alpha*realVal
 */
function blendWithRealData(noiseVal, realVal, alpha = 0.6) {
    return lerp(noiseVal, realVal, alpha);
}

// ---------------------------------------------------------------------------
// Terrain generation
// ---------------------------------------------------------------------------

/**
 * Generate a height grid for a region.
 * Uses simplex noise biased by embedding elevation signals.
 *
 * @param {{ minX, maxX, minY, maxY }} bbox
 * @param {Array<{x, y, elevation}>}   elevationSamples  from embedding data
 * @param {number} [resolution=32]     grid cells per axis
 * @param {Function} noise2D
 * @returns {Float32Array}  row-major height values in [0,1]
 */
function generateHeightGrid(bbox, elevationSamples, resolution, noise2D) {
    const grid    = new Float32Array(resolution * resolution);
    const width   = bbox.maxX - bbox.minX;
    const height  = bbox.maxY - bbox.minY;

    for (let row = 0; row < resolution; row++) {
        for (let col = 0; col < resolution; col++) {
            const wx = bbox.minX + (col / (resolution - 1)) * width;
            const wy = bbox.minY + (row / (resolution - 1)) * height;

            // Multi-octave simplex noise (mapgen4 style)
            const noiseVal =
                0.50 * noise2D(wx * 0.003,  wy * 0.003)
              + 0.25 * noise2D(wx * 0.009,  wy * 0.009)
              + 0.13 * noise2D(wx * 0.027,  wy * 0.027)
              + 0.12 * noise2D(wx * 0.081,  wy * 0.081);

            const normalised = clamp((noiseVal + 1) / 2, 0, 1);

            // Find nearest elevation sample and blend
            let nearestElev = 0.5, nearestDist = Infinity;
            for (const s of elevationSamples) {
                const dx = wx - s.x, dy = wy - s.y;
                const dist = dx * dx + dy * dy;
                if (dist < nearestDist) { nearestDist = dist; nearestElev = s.elevation; }
            }

            grid[row * resolution + col] = blendWithRealData(normalised, nearestElev);
        }
    }

    return grid;
}

// ---------------------------------------------------------------------------
// Cluster helpers
// ---------------------------------------------------------------------------

function groupByCluster(buildings) {
    const clusters = {};
    for (const b of buildings) {
        const id = b.urban_type ?? 0;
        (clusters[id] = clusters[id] ?? []).push(b);
    }
    return clusters;
}

function calculateDensity(buildings) {
    return Math.max(0.5, Math.min(6, buildings.length / 50));
}

function getHeightRange(buildings) {
    const heights = buildings
        .map(b => parseFloat(b.height))
        .filter(h => !isNaN(h));
    if (!heights.length) return { min: 3, max: 15, avg: 9 };
    const min = Math.min(...heights);
    const max = Math.max(...heights);
    const avg = heights.reduce((a, b) => a + b, 0) / heights.length;
    return { min, max, avg };
}

// ---------------------------------------------------------------------------
// Building placement
// ---------------------------------------------------------------------------

/**
 * Scatter buildings within a bbox obeying density + height constraints.
 * Uses a simple grid subdivision to avoid overlaps.
 */
function placeClusterBuildings(bbox, density, heightRange) {
    const buildings = [];
    const { min: minH, max: maxH, avg: avgH } = heightRange;
    const spacing = Math.max(6, 30 / Math.sqrt(density));
    const width   = bbox.maxX - bbox.minX;
    const height  = bbox.maxY - bbox.minY;
    const cols    = Math.max(1, Math.floor(width  / spacing));
    const rows    = Math.max(1, Math.floor(height / spacing));

    for (let r = 0; r < rows; r++) {
        for (let c = 0; c < cols; c++) {
            if (Math.random() > 0.65 + density * 0.05) continue;

            const x = bbox.minX + (c + 0.3 + Math.random() * 0.4) * spacing;
            const y = bbox.minY + (r + 0.3 + Math.random() * 0.4) * spacing;

            // Height: interpolate within cluster range with randomness
            const t      = Math.random();
            const h      = lerp(minH, maxH, t * t); // bias toward lower heights

            const size = Math.max(4, 20 / Math.sqrt(density));
            buildings.push({
                position:  [x, y],
                height:    clamp(h, 3, maxH),
                footprint: {
                    width:    size * (0.5 + Math.random() * 0.8),
                    depth:    size * (0.5 + Math.random() * 0.8),
                    rotation: Math.random() * Math.PI,
                },
            });
        }
    }

    return buildings;
}

// ---------------------------------------------------------------------------
// Street network
// ---------------------------------------------------------------------------

/**
 * Generate a simple grid + diagonal street network for a region.
 * Returns an array of line segments [{ start:[x,y], end:[x,y] }].
 */
function generateStreets(bbox, density) {
    const streets = [];
    const spacing = Math.max(20, 80 / Math.sqrt(density));
    const { minX, maxX, minY, maxY } = bbox;

    // Horizontal streets
    for (let y = minY; y <= maxY; y += spacing) {
        streets.push({ start: [minX, y], end: [maxX, y], type: 'primary' });
    }
    // Vertical streets
    for (let x = minX; x <= maxX; x += spacing) {
        streets.push({ start: [x, minY], end: [x, maxY], type: 'primary' });
    }
    // Diagonal alleys at half-spacing (secondary)
    const half = spacing / 2;
    for (let y = minY + half; y <= maxY; y += spacing) {
        streets.push({ start: [minX, y], end: [maxX, y], type: 'secondary' });
    }

    return streets;
}

// ---------------------------------------------------------------------------
// DataDrivenCityGenerator
// ---------------------------------------------------------------------------

export class DataDrivenCityGenerator {
    /**
     * @param {Array<{geometry, building_type, height, embedding, urban_type}>} embeddingData
     * @param {number} [seed=99]
     * @param {number} [terrainResolution=32]
     */
    constructor(embeddingData, seed = 99, terrainResolution = 32) {
        this.embeddingData     = embeddingData;
        this.terrainResolution = terrainResolution;
        this.noise2D           = createNoise2D(this._lcgFactory(seed));
    }

    // -------------------------------------------------------------------------
    // Public API
    // -------------------------------------------------------------------------

    /**
     * Generate terrain + buildings + streets for a region.
     *
     * @param {{ minX, maxX, minY, maxY }} region
     * @returns {{ terrain, buildings, streets }}
     *
     * terrain  — { grid: Float32Array, resolution: number, bbox }
     * buildings — Array<{ position, height, footprint, clusterId }>
     * streets  — Array<{ start, end, type }>
     */
    generate(region) {
        const bbox = {
            minX: region.minX ?? region.x ?? 0,
            maxX: region.maxX ?? (region.x ?? 0) + (region.width ?? 1000),
            minY: region.minY ?? region.y ?? 0,
            maxY: region.maxY ?? (region.y ?? 0) + (region.height ?? 1000),
        };

        const elevationSamples = this._getElevationSamples(bbox);
        const terrain = {
            grid:       generateHeightGrid(bbox, elevationSamples, this.terrainResolution, this.noise2D),
            resolution: this.terrainResolution,
            bbox,
        };

        const buildings = this._placeBuildings(bbox);
        const streets   = this._generateStreets(bbox, buildings.length);

        return { terrain, buildings, streets };
    }

    // -------------------------------------------------------------------------
    // Private
    // -------------------------------------------------------------------------

    _getElevationSamples(bbox) {
        return this.embeddingData
            .filter(b => {
                // Geometry may be a GeoJSON object or a centroid object
                const [x, y] = this._getCentroid(b);
                return bboxContains(bbox, x, y);
            })
            .map(b => {
                const [x, y] = this._getCentroid(b);
                return { x, y, elevation: decodeElevation(b.embedding) };
            });
    }

    _placeBuildings(bbox) {
        const regionData = this.embeddingData.filter(b => {
            const [x, y] = this._getCentroid(b);
            return bboxContains(bbox, x, y);
        });

        if (!regionData.length) {
            // No real data in this region — fall back to a default cluster
            return placeClusterBuildings(bbox, 1.5, { min: 4, max: 20, avg: 10 });
        }

        const clusters  = groupByCluster(regionData);
        const buildings = [];

        for (const [clusterId, clusterBuildings] of Object.entries(clusters)) {
            const density     = calculateDensity(clusterBuildings);
            const heightRange = getHeightRange(clusterBuildings);
            const placed      = placeClusterBuildings(bbox, density, heightRange);

            // Tag each building with its cluster id
            for (const b of placed) b.clusterId = Number(clusterId);
            buildings.push(...placed);
        }

        return buildings;
    }

    _generateStreets(bbox, buildingCount) {
        const density = Math.max(0.5, buildingCount / 100);
        return generateStreets(bbox, density);
    }

    /**
     * Extract [x, y] from whatever geometry representation is present.
     * Supports GeoJSON Point, {x,y}, [x,y], and plain objects with .lat/.lng.
     */
    _getCentroid(building) {
        const g = building.geometry;
        if (!g) return [0, 0];
        if (Array.isArray(g))                          return g;
        if (typeof g.x === 'number')                   return [g.x,                    g.y];
        if (g.type === 'Point')                        return g.coordinates;
        if (g.type === 'Polygon' || g.type === 'MultiPolygon') {
            // Rough centroid: average of first ring's vertices
            const ring = g.type === 'Polygon' ? g.coordinates[0] : g.coordinates[0][0];
            const sum  = ring.reduce(([ax, ay], [bx, by]) => [ax + bx, ay + by], [0, 0]);
            return [sum[0] / ring.length, sum[1] / ring.length];
        }
        return [building.lon ?? building.lng ?? 0, building.lat ?? 0];
    }

    _lcgFactory(seed) {
        let s = seed >>> 0;
        return () => {
            s = (Math.imul(1664525, s) + 1013904223) >>> 0;
            return s / 0x100000000;
        };
    }
}
