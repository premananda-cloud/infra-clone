/**
 * App.jsx  — Digital Twin City MVP
 *
 * Three.js scene driven by two generation backends:
 *   • Mapgen4Adapter  (UrbanGenerator)   — Delaunay/Voronoi street networks
 *   • MetroMapAdapter (DataDrivenCityGenerator) — terrain + building placement
 *
 * The app renders a low-poly 3D city from AlphaEarth embedding data.
 * Drop your exported city_buildings_with_embeddings.json into
 * src/data/city_rules.json to load real data; the app ships with a
 * built-in synthetic fallback so it works out of the box.
 *
 * Controls: orbit (left-drag), zoom (scroll), pan (right-drag)
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { UrbanGenerator }          from './generators/Mapgen4Adapter.js';
import { DataDrivenCityGenerator } from './generators/MetroMapAdapter.js';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const WORLD_SIZE   = 1000;
const GRID_CELLS   = 40;   // terrain grid resolution
const TERRAIN_RES  = 32;
const CLUSTER_COLOURS = [
    0x4a7c59,  // 0 — green / park
    0x8b7355,  // 1 — brown / residential
    0x6b8cba,  // 2 — blue  / commercial
    0xc0784a,  // 3 — orange/ industrial
    0x9b7eb8,  // 4 — purple/ mixed-use
];

// ---------------------------------------------------------------------------
// Synthetic fallback data (no JSON file needed)
// ---------------------------------------------------------------------------

function generateFallbackData(n = 300) {
    const types = ['residential', 'commercial', 'industrial', 'retail', 'office'];
    return Array.from({ length: n }, (_, i) => ({
        geometry:      { type: 'Point', coordinates: [Math.random() * WORLD_SIZE, Math.random() * WORLD_SIZE] },
        building_type: types[Math.floor(Math.random() * types.length)],
        height:        5 + Math.random() * 40,
        urban_type:    Math.floor(Math.random() * 5),
        embedding:     Array.from({ length: 64 }, () => Math.random() * 2 - 1),
    }));
}

// ---------------------------------------------------------------------------
// Three.js scene helpers
// ---------------------------------------------------------------------------

function buildTerrain(terrain) {
    const { grid, resolution, bbox } = terrain;
    const width  = bbox.maxX - bbox.minX;
    const depth  = bbox.maxY - bbox.minY;

    const geo = new THREE.PlaneGeometry(width, depth, resolution - 1, resolution - 1);
    geo.rotateX(-Math.PI / 2);

    const pos = geo.attributes.position;
    for (let i = 0; i < pos.count; i++) {
        const elevation = grid[i] ?? 0;
        pos.setY(i, elevation * 30 - 5); // scale to world height
    }
    pos.needsUpdate = true;
    geo.computeVertexNormals();

    const mat  = new THREE.MeshLambertMaterial({ color: 0x4a6741, wireframe: false });
    const mesh = new THREE.Mesh(geo, mat);
    mesh.position.set(bbox.minX + width / 2, 0, bbox.minY + depth / 2);
    mesh.receiveShadow = true;
    return mesh;
}

function buildBuilding(b) {
    const [wx, wz] = b.position;
    const { width: fw, depth: fd, rotation: fr } = b.footprint;
    const h = b.height;

    const geo  = new THREE.BoxGeometry(fw, h, fd);
    const col  = CLUSTER_COLOURS[b.clusterId ?? 0] ?? 0x888888;
    const mat  = new THREE.MeshLambertMaterial({ color: col });
    const mesh = new THREE.Mesh(geo, mat);

    mesh.position.set(wx, h / 2, wz);
    mesh.rotation.y = fr;
    mesh.castShadow    = true;
    mesh.receiveShadow = true;
    return mesh;
}

function buildStreets(streets) {
    const group = new THREE.Group();
    const matP  = new THREE.LineBasicMaterial({ color: 0xcccccc });
    const matS  = new THREE.LineBasicMaterial({ color: 0x999999 });

    for (const s of streets) {
        const pts = [
            new THREE.Vector3(s.start[0], 0.2, s.start[1]),
            new THREE.Vector3(s.end[0],   0.2, s.end[1]),
        ];
        const geo  = new THREE.BufferGeometry().setFromPoints(pts);
        const line = new THREE.Line(geo, s.type === 'primary' ? matP : matS);
        group.add(line);
    }

    return group;
}

function buildVoronoiDebug(voronoi) {
    const { points } = voronoi;
    const group = new THREE.Group();
    const mat   = new THREE.PointsMaterial({ color: 0xffaa00, size: 3 });
    const verts = [];

    for (let i = 0; i < points.length / 2; i++) {
        verts.push(points[i * 2], 0.5, points[i * 2 + 1]);
    }

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3));
    group.add(new THREE.Points(geo, mat));
    return group;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function App() {
    const mountRef      = useRef(null);
    const sceneRef      = useRef(null);
    const rendererRef   = useRef(null);
    const cameraRef     = useRef(null);
    const controlsRef   = useRef(null);
    const animFrameRef  = useRef(null);

    const [status,     setStatus]     = useState('Initialising…');
    const [mode,       setMode]       = useState('metromap');   // 'metromap' | 'mapgen4'
    const [showStreets, setShowStreets] = useState(true);
    const [showVoronoi, setShowVoronoi] = useState(false);
    const [dataSize,   setDataSize]   = useState(300);
    const [seed,       setSeed]       = useState(42);

    // -----------------------------------------------------------------------
    // Scene bootstrap (runs once)
    // -----------------------------------------------------------------------

    useEffect(() => {
        const el = mountRef.current;
        const W  = el.clientWidth;
        const H  = el.clientHeight;

        // Renderer
        const renderer = new THREE.WebGLRenderer({ antialias: true });
        renderer.setSize(W, H);
        renderer.setPixelRatio(window.devicePixelRatio);
        renderer.shadowMap.enabled = true;
        renderer.shadowMap.type    = THREE.PCFSoftShadowMap;
        renderer.setClearColor(0x0f172a);
        el.appendChild(renderer.domElement);
        rendererRef.current = renderer;

        // Camera
        const camera = new THREE.PerspectiveCamera(60, W / H, 1, 5000);
        camera.position.set(500, 400, 900);
        camera.lookAt(500, 0, 500);
        cameraRef.current = camera;

        // Controls
        const controls = new OrbitControls(camera, renderer.domElement);
        controls.target.set(500, 0, 500);
        controls.maxPolarAngle = Math.PI / 2 - 0.05;
        controls.update();
        controlsRef.current = controls;

        // Scene
        const scene = new THREE.Scene();
        scene.fog   = new THREE.Fog(0x0f172a, 800, 2500);

        // Lighting
        const ambient = new THREE.AmbientLight(0x334466, 0.8);
        scene.add(ambient);

        const sun = new THREE.DirectionalLight(0xffeedd, 1.4);
        sun.position.set(400, 600, 300);
        sun.castShadow = true;
        sun.shadow.mapSize.width  = 2048;
        sun.shadow.mapSize.height = 2048;
        sun.shadow.camera.near    = 10;
        sun.shadow.camera.far     = 2000;
        sun.shadow.camera.left    = -600;
        sun.shadow.camera.right   =  600;
        sun.shadow.camera.top     =  600;
        sun.shadow.camera.bottom  = -600;
        scene.add(sun);

        sceneRef.current = scene;

        // Resize handler
        const onResize = () => {
            const w = el.clientWidth, h = el.clientHeight;
            camera.aspect = w / h;
            camera.updateProjectionMatrix();
            renderer.setSize(w, h);
        };
        window.addEventListener('resize', onResize);

        // Render loop
        const animate = () => {
            animFrameRef.current = requestAnimationFrame(animate);
            controls.update();
            renderer.render(scene, camera);
        };
        animate();

        return () => {
            cancelAnimationFrame(animFrameRef.current);
            window.removeEventListener('resize', onResize);
            renderer.dispose();
            el.removeChild(renderer.domElement);
        };
    }, []);

    // -----------------------------------------------------------------------
    // City generation — reruns when mode / seed / dataSize change
    // -----------------------------------------------------------------------

    const regenerate = useCallback(() => {
        const scene = sceneRef.current;
        if (!scene) return;

        // Clear previous city objects (keep lights)
        const toRemove = scene.children.filter(c => c.userData.cityObject);
        toRemove.forEach(c => {
            scene.remove(c);
            c.traverse(o => { if (o.geometry) o.geometry.dispose(); });
        });

        setStatus('Generating…');

        // Small timeout so React can repaint the status
        setTimeout(() => {
            try {
                const embeddingData = generateFallbackData(dataSize);
                const region = { minX: 0, maxX: WORLD_SIZE, minY: 0, maxY: WORLD_SIZE };

                const addCity = (city) => {
                    if (city.terrain) {
                        const t = buildTerrain(city.terrain);
                        t.userData.cityObject = true;
                        scene.add(t);
                    }

                    if (city.buildings) {
                        city.buildings.forEach(b => {
                            const m = buildBuilding(b);
                            m.userData.cityObject = true;
                            scene.add(m);
                        });
                    }

                    if (showStreets && city.streets) {
                        const s = buildStreets(city.streets);
                        s.userData.cityObject = true;
                        scene.add(s);
                    }

                    if (showVoronoi && city.voronoi) {
                        const v = buildVoronoiDebug(city.voronoi);
                        v.userData.cityObject = true;
                        scene.add(v);
                    }

                    setStatus(`Done — ${city.buildings?.length ?? 0} buildings`);
                };

                if (mode === 'metromap') {
                    const gen  = new DataDrivenCityGenerator(embeddingData, seed, TERRAIN_RES);
                    const city = gen.generate(region);
                    addCity(city);

                } else {
                    // mapgen4 mode: generate 5 districts, one per cluster
                    const gen  = new UrbanGenerator(embeddingData, WORLD_SIZE, seed);
                    let totalBuildings = 0;
                    const voronoiForDebug = [];

                    const cx = [250, 750, 250, 750, 500];
                    const cy = [250, 250, 750, 750, 500];

                    for (let cluster = 0; cluster < 5; cluster++) {
                        const profiles = gen.clusterProfiles;
                        if (!profiles[cluster]) continue;

                        const result = gen.generateDistrict(cx[cluster], cy[cluster], cluster);
                        result.buildings.forEach(b => {
                            const m = buildBuilding(b);
                            m.userData.cityObject = true;
                            scene.add(m);
                            totalBuildings++;
                        });
                        voronoiForDebug.push(result.voronoi);
                    }

                    if (showVoronoi) {
                        for (const v of voronoiForDebug) {
                            const vMesh = buildVoronoiDebug(v);
                            vMesh.userData.cityObject = true;
                            scene.add(vMesh);
                        }
                    }

                    // Flat ground plane for mapgen4 mode
                    const ground = new THREE.Mesh(
                        new THREE.PlaneGeometry(WORLD_SIZE, WORLD_SIZE),
                        new THREE.MeshLambertMaterial({ color: 0x2d4a27 })
                    );
                    ground.rotation.x    = -Math.PI / 2;
                    ground.position.set(WORLD_SIZE / 2, -0.1, WORLD_SIZE / 2);
                    ground.receiveShadow = true;
                    ground.userData.cityObject = true;
                    scene.add(ground);

                    setStatus(`Done — ${totalBuildings} buildings`);
                }
            } catch (err) {
                console.error(err);
                setStatus(`Error: ${err.message}`);
            }
        }, 30);
    }, [mode, seed, dataSize, showStreets, showVoronoi]);

    // Initial generation
    useEffect(() => { regenerate(); }, [regenerate]);

    // -----------------------------------------------------------------------
    // UI
    // -----------------------------------------------------------------------

    return (
        <div style={{ width: '100vw', height: '100vh', background: '#0f172a', position: 'relative', fontFamily: 'system-ui, sans-serif' }}>

            {/* Three.js canvas */}
            <div ref={mountRef} style={{ width: '100%', height: '100%' }} />

            {/* HUD panel */}
            <div style={{
                position: 'absolute', top: 16, left: 16,
                background: 'rgba(15,23,42,0.85)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 10, padding: '14px 18px',
                color: '#e2e8f0', fontSize: 13, width: 240,
                backdropFilter: 'blur(8px)',
            }}>
                <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 12, color: '#93c5fd' }}>
                    🏙 Digital Twin City
                </div>

                {/* Mode */}
                <Label>Generator</Label>
                <ButtonGroup>
                    <ModeBtn active={mode === 'metromap'} onClick={() => setMode('metromap')}>
                        MetroMap
                    </ModeBtn>
                    <ModeBtn active={mode === 'mapgen4'}  onClick={() => setMode('mapgen4')}>
                        Mapgen4
                    </ModeBtn>
                </ButtonGroup>

                {/* Seed */}
                <Label>Seed: {seed}</Label>
                <input type="range" min={1} max={999} value={seed}
                    onChange={e => setSeed(Number(e.target.value))}
                    style={{ width: '100%', accentColor: '#3b82f6', marginBottom: 10 }} />

                {/* Data size */}
                <Label>Buildings (synthetic): {dataSize}</Label>
                <input type="range" min={50} max={800} step={50} value={dataSize}
                    onChange={e => setDataSize(Number(e.target.value))}
                    style={{ width: '100%', accentColor: '#3b82f6', marginBottom: 10 }} />

                {/* Toggles */}
                <Toggle checked={showStreets} onChange={setShowStreets}>Show streets</Toggle>
                <Toggle checked={showVoronoi} onChange={setShowVoronoi}>Show Voronoi sites</Toggle>

                {/* Regenerate */}
                <button onClick={regenerate} style={{
                    marginTop: 12, width: '100%',
                    background: '#3b82f6', color: '#fff',
                    border: 'none', borderRadius: 6,
                    padding: '8px 0', fontWeight: 600, cursor: 'pointer', fontSize: 13,
                }}>
                    ↻ Regenerate
                </button>

                {/* Status */}
                <div style={{ marginTop: 10, fontSize: 11, color: '#94a3b8' }}>{status}</div>
            </div>

            {/* Cluster legend */}
            <div style={{
                position: 'absolute', bottom: 16, left: 16,
                background: 'rgba(15,23,42,0.85)',
                border: '1px solid rgba(255,255,255,0.1)',
                borderRadius: 10, padding: '10px 14px',
                color: '#e2e8f0', fontSize: 12,
                backdropFilter: 'blur(8px)',
            }}>
                {['Park / greenspace', 'Residential', 'Commercial', 'Industrial', 'Mixed-use'].map((label, i) => (
                    <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                        <div style={{
                            width: 12, height: 12, borderRadius: 2, flexShrink: 0,
                            background: '#' + CLUSTER_COLOURS[i].toString(16).padStart(6, '0'),
                        }} />
                        <span>{label}</span>
                    </div>
                ))}
            </div>

            {/* Controls hint */}
            <div style={{
                position: 'absolute', bottom: 16, right: 16,
                color: 'rgba(148,163,184,0.6)', fontSize: 11, textAlign: 'right',
            }}>
                Drag to orbit · Scroll to zoom · Right-drag to pan
            </div>
        </div>
    );
}

// ---------------------------------------------------------------------------
// Tiny UI atoms
// ---------------------------------------------------------------------------

function Label({ children }) {
    return <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 4 }}>{children}</div>;
}

function ButtonGroup({ children }) {
    return <div style={{ display: 'flex', gap: 6, marginBottom: 12 }}>{children}</div>;
}

function ModeBtn({ active, onClick, children }) {
    return (
        <button onClick={onClick} style={{
            flex: 1, padding: '6px 0',
            background: active ? '#3b82f6' : 'rgba(255,255,255,0.07)',
            color: active ? '#fff' : '#94a3b8',
            border: active ? '1px solid #3b82f6' : '1px solid rgba(255,255,255,0.1)',
            borderRadius: 6, fontSize: 12, fontWeight: active ? 600 : 400,
            cursor: 'pointer',
        }}>
            {children}
        </button>
    );
}

function Toggle({ checked, onChange, children }) {
    return (
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, cursor: 'pointer' }}>
            <input type="checkbox" checked={checked}
                onChange={e => onChange(e.target.checked)}
                style={{ accentColor: '#3b82f6' }} />
            <span style={{ fontSize: 12 }}>{children}</span>
        </label>
    );
}
