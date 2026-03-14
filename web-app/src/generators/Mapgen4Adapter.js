/**
 * Mapgen4Adapter.js
 *
 * Adapts mapgen4's core algorithms (Delaunay triangulation, Voronoi diagrams,
 * Poisson disc sampling) for data-driven urban generation.
 *
 * Uses the same underlying libraries as mapgen4:
 *   - delaunator                     (Delaunay triangulation / Voronoi)
 *   - fast-2d-poisson-disk-sampling  (realistic point distribution)
 *   - simplex-noise                  (terrain noise / jitter)
 *
 * Install: npm install delaunator fast-2d-poisson-disk-sampling simplex-noise
 */

import Delaunator from 'delaunator';
import PoissonDiskSampling from 'fast-2d-poisson-disk-sampling';
import { createNoise2D } from 'simplex-noise';

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/** L2 distance between two embedding vectors. */
function embeddingDistance(a, b) {
    if (!a || !b || a.length !== b.length) return Infinity;
    let sum = 0;
    for (let i = 0; i < a.length; i++) {
        const d = a[i] - b[i];
        sum += d * d;
    }
    return Math.sqrt(sum);
}

/** Nearest-centroid classifier — returns the index of the closest centroid. */
function nearestCentroid(centroids, embedding) {
    let best = 0;
    let bestDist = Infinity;
    for (let i = 0; i < centroids.length; i++) {
        const d = embeddingDistance(centroids[i], embedding);
        if (d < bestDist) { bestDist = d; best = i; }
    }
    return best;
}

/** Component-wise mean of an array of embedding vectors. */
function meanEmbedding(embeddings) {
    if (!embeddings.length) return [];
    const dim = embeddings[0].length;
    const sum = new Array(dim).fill(0);
    for (const e of embeddings) {
        for (let i = 0; i < dim; i++) sum[i] += e[i];
    }
    return sum.map(v => v / embeddings.length);
}

/**
 * For every input point, collect the circumcentres of all triangles that
 * touch it. These form the Voronoi cell polygon.
 * Pattern taken from mapgen4/geometry.ts.
 */
function buildVoronoiCells(flatPoints, delaunay) {
    const { triangles } = delaunay;
    const numPoints = flatPoints.length / 2;

    // Circumcentre for each triangle
    const circumcentres = [];
    for (let t = 0; t < triangles.length / 3; t++) {
        const a = triangles[t * 3];
        const b = triangles[t * 3 + 1];
        const c = triangles[t * 3 + 2];
        const ax = flatPoints[a * 2], ay = flatPoints[a * 2 + 1];
        const bx = flatPoints[b * 2], by = flatPoints[b * 2 + 1];
        const cx = flatPoints[c * 2], cy = flatPoints[c * 2 + 1];
        const D = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by));
        if (Math.abs(D) < 1e-10) {
            circumcentres.push([(ax + bx + cx) / 3, (ay + by + cy) / 3]);
        } else {
            const ux = ((ax * ax + ay * ay) * (by - cy)
                      + (bx * bx + by * by) * (cy - ay)
                      + (cx * cx + cy * cy) * (ay - by)) / D;
            const uy = ((ax * ax + ay * ay) * (cx - bx)
                      + (bx * bx + by * by) * (ax - cx)
                      + (cx * cx + cy * cy) * (bx - ax)) / D;
            circumcentres.push([ux, uy]);
        }
    }

    // point → list of triangle indices
    const pointTriangles = Array.from({ length: numPoints }, () => []);
    for (let i = 0; i < triangles.length; i++) {
        pointTriangles[triangles[i]].push(Math.floor(i / 3));
    }

    return { circumcentres, pointTriangles };
}

// ---------------------------------------------------------------------------
// UrbanGenerator
// ---------------------------------------------------------------------------

export class UrbanGenerator {
    /**
     * @param {Array<{geometry, building_type, height, embedding, urban_type}>} embeddingData
     *   Rows exported by analyse_clusters.py as JSON.
     * @param {number} [worldSize=1000]  Side length of the generation canvas.
     * @param {number} [seed=42]
     */
    constructor(embeddingData, worldSize = 1000, seed = 42) {
        this.data        = embeddingData;
        this.worldSize   = worldSize;
        this.noise2D     = createNoise2D(this._lcgFactory(seed));

        this.clusterProfiles = this._buildClusterProfiles();
        // Ordered centroid list for the classifier
        this.centroids = Object.values(this.clusterProfiles)
                               .sort((a, b) => a.id - b.id)
                               .map(p => p.centroid);
    }

    // -------------------------------------------------------------------------
    // Public API
    // -------------------------------------------------------------------------

    /**
     * Generate a district centred at (cx, cy) for the given cluster.
     * Returns { streetSites, voronoi, buildings }.
     */
    generateDistrict(cx, cy, clusterId) {
        const profile = this.clusterProfiles[clusterId];
        if (!profile) throw new Error(`Unknown clusterId: ${clusterId}`);

        const streetSites = this.generateStreetSites(cx, cy, profile.density);
        const voronoi     = this.computeVoronoi(streetSites);
        const buildings   = this._generateBuildings(profile, voronoi);

        return { streetSites, voronoi, buildings };
    }

    /**
     * Nearest-centroid embedding classifier.
     * @param {number[]} embedding  64-dim AlphaEarth vector
     * @returns {number} cluster id
     */
    predictCluster(embedding) {
        return nearestCentroid(this.centroids, embedding);
    }

    /**
     * Poisson disc street-site generation.
     * Uses the same fast-2d-poisson-disk-sampling library as mapgen4.
     * Returns a flat Float64Array [x0,y0, x1,y1, …] for Delaunator.
     *
     * @param {number} cx           World-space centre X
     * @param {number} cy           World-space centre Y
     * @param {number} [density=1]  Cluster density (higher → closer buildings)
     */
    generateStreetSites(cx, cy, density = 1) {
        const minDist  = Math.max(8, 80 / Math.sqrt(density));
        const halfSize = Math.min(this.worldSize / 2, 400);

        const pds = new PoissonDiskSampling({
            shape:       [halfSize * 2, halfSize * 2],
            minDistance: minDist,
            maxDistance: minDist * 2.5,
            tries:       20,
        });

        const rawPoints = pds.fill();   // [[x, y], …]
        const flat = [];

        for (const [lx, ly] of rawPoints) {
            const wx = cx - halfSize + lx;
            const wy = cy - halfSize + ly;
            // Simplex noise jitter — same technique as mapgen4/mesh.ts
            const jitter = minDist * 0.15;
            flat.push(
                wx + this.noise2D(wx * 0.01,       wy * 0.01)       * jitter,
                wy + this.noise2D(wx * 0.01 + 100, wy * 0.01 + 100) * jitter,
            );
        }

        return flat;
    }

    /**
     * Delaunay triangulation + Voronoi cell extraction.
     * @param {number[]} flatPoints  [x0,y0, x1,y1, …]
     * @returns {{ delaunay, circumcentres, pointTriangles, points }}
     */
    computeVoronoi(flatPoints) {
        const delaunay = new Delaunator(flatPoints);
        const { circumcentres, pointTriangles } = buildVoronoiCells(flatPoints, delaunay);
        return { delaunay, circumcentres, pointTriangles, points: flatPoints };
    }

    // -------------------------------------------------------------------------
    // Private
    // -------------------------------------------------------------------------

    _buildClusterProfiles() {
        const profiles = {};

        for (const b of this.data) {
            const id = b.urban_type ?? 0;
            if (!profiles[id]) {
                profiles[id] = {
                    id,
                    buildings:  [],
                    embeddings: [],
                    heights:    [],
                    types:      {},
                };
            }
            const p = profiles[id];
            p.buildings.push(b);
            if (Array.isArray(b.embedding) && b.embedding.length) {
                p.embeddings.push(b.embedding);
            }
            const h = parseFloat(b.height);
            if (!isNaN(h)) p.heights.push(h);
            p.types[b.building_type ?? 'unknown'] =
                (p.types[b.building_type ?? 'unknown'] ?? 0) + 1;
        }

        for (const p of Object.values(profiles)) {
            p.centroid     = meanEmbedding(p.embeddings);
            p.avgHeight    = p.heights.length
                ? p.heights.reduce((a, b) => a + b, 0) / p.heights.length
                : 10;
            p.heightStdDev = p.heights.length > 1
                ? Math.sqrt(p.heights.reduce((acc, h) => acc + (h - p.avgHeight) ** 2, 0) / p.heights.length)
                : 3;
            p.dominantType = Object.entries(p.types)
                .sort((a, b) => b[1] - a[1])[0]?.[0] ?? 'residential';
            // Density: buildings per 50 as a normalised proxy
            p.density = Math.max(0.5, Math.min(6, p.buildings.length / 50));
        }

        return profiles;
    }

    _generateBuildings(profile, voronoi) {
        const buildings = [];
        const { points } = voronoi;
        const numSites   = points.length / 2;

        for (let i = 0; i < numSites; i++) {
            const px = points[i * 2];
            const py = points[i * 2 + 1];

            // Not every Voronoi site becomes a building
            const placementChance = Math.min(0.9, 0.55 + (profile.density - 1) * 0.08);
            if (Math.random() > placementChance) continue;

            // Height: gaussian-ish spread around cluster mean
            const heightVariation = (Math.random() + Math.random() - 1) * profile.heightStdDev;
            const height = Math.max(3, profile.avgHeight + heightVariation);

            // Footprint rectangle, size inversely proportional to density
            const baseSize = Math.max(4, 22 / Math.sqrt(profile.density));
            const w   = baseSize * (0.5 + Math.random() * 0.9);
            const d   = baseSize * (0.5 + Math.random() * 0.9);
            const rot = Math.random() * Math.PI;

            buildings.push({
                position:     [px, py],
                height,
                footprint:    { width: w, depth: d, rotation: rot },
                buildingType: profile.dominantType,
                clusterId:    profile.id,
            });
        }

        return buildings;
    }

    /** Returns a seeded () => [0,1) function for simplex-noise. */
    _lcgFactory(seed) {
        let s = seed >>> 0;
        return () => {
            s = (Math.imul(1664525, s) + 1013904223) >>> 0;
            return s / 0x100000000;
        };
    }
}
