# E07 Fullscan — Analysis Notes

Chronological development diary — results, discussions, decisions, and dead ends.
Technical API reference: README.md.

**Started:** 2026-05-08

---

## Reference

### Scan Geometry

| Item | Value |
|---|---|
| Plate | MOD108 / PL12 / tohoku-v1 / AREA00 |
| Views | 2025 (45 × 45 grid) |
| FOV spacing | ~0.5 mm |
| FOV size | ~594 × 594 μm |
| **Pixel scale** | **0.29 μm/px** (scanner JSON says 3.0 — wrong) |
| Emulsion depth | ~150 μm |
| Slices | ~100, z-spacing ~1.5 μm/slice |

Confirmed 0.29 μm/px from scan geometry: 2048 px × 0.29 = 594 μm ≈ 0.5 mm FOV spacing.

### Pipeline

```
SPNG images
    │  [per slice per view]
    ▼  Z-projection → fog removal → Otsu threshold → noise removal
    │  HoughLinesP
    ▼  Track segments  (chunk_NNNN.parquet, ~24M tracks total)
    │  quality metrics: length_px, mean_intens, angle_deg, n_grains, grain_density
    ▼  pairwise intersection + endpoint check
    │  Per-slice vertex candidates  (vertices.parquet)
    ▼  XY proximity merge across z-slices
    Merged vertex candidates  (vertices_merged.parquet)
```

![Processing pipeline](docs/pipeline.png)

### Physics Goals

**Current phase**: efficiency-first selection of *any* reaction vertex.
Targets: beam interactions, single-Λ hypernuclei, α decay chains, nuclear stars.

**Ultimate goal**: double hypernuclei (ΛΛ) search.
Signature: two connected vertices separated by ~100–500 μm (30–167 px):
1. **Primary vertex** — beam + target → ΛΛ-hypernucleus + other particles
2. **Secondary vertex** — hypernucleus weak decay (kink or small star)

### Beam Direction

Beam travels in the emulsion plane along X (horizontal in image).
22% of all tracks have `angle_deg < 15°` or `> 165°` (beam direction).
`beam_angle_cut = 15°` removes these.

---

## Development Log

---

## 2026-05-08 — First track analysis run; pixel scale correction

**What was done:**
- Ran full `e07analyze` on 2025 views → `results/merged.parquet` (~24M tracks).
- Discovered pixel scale error in scanner JSON: metadata says 3.0 μm/px but scan geometry
  gives **0.29 μm/px**. Corrected `px_scale_um` in `config/default.yaml`.
- Consequence: `grain_density` in existing parquet is 10× too low (computed with 3.0).
  Use `n_grains` directly until track analysis is re-run with 0.29.

**Track quality metrics confirmed:**
- `mean_intens` is independent of px_scale → reliable for quality cuts.
- `grain_density` = n_grains / (length_px × px_scale) × 100 grains/100 μm;
  corrected values will be meaningful for particle ID.
- `width_px`: transverse spread of grain centroids; heavier/slower tracks are wider.

**Hough parameter tuning (visual check):**

| Parameter | Old | New | Reason |
|---|---|---|---|
| `hough_thr` | 20 | 35 | Reduce noise track count |
| `hough_ml` | 25 px | 50 px | 25 px = 7.3 μm; too many noise segments |
| `hough_mg` | 4 | 5 | Marginal improvement |
| `grain_radius` | 10 px | 15 px | Better grain association at 0.29 μm/px |

**v1 vertex run (first attempt):**
- Parameters: `min_len=100, min_intens=12, max_ep=100`, no beam cut
- Result: **95,160 raw → 8,468 merged**
- Observation: very conservative; missed α tracks (~86 px < 100 px cutoff).

---

## 2026-05-09 — Vertex finding v2; parameter relaxation

**What was done:**
- Relaxed vertex finding parameters for efficiency-first approach:
  - `min_len_px`: 100 → **50 px** (catches α tracks at ~86 px)
  - `min_intens`: 12 → **10.0**
  - `max_ep`: 100 → **150 px**
  - `beam_angle_cut`: 0 → **15°** (remove beam-parallel tracks)
- v2 result: **6,976,451 raw → 642,558 merged** — explosion.

**Root cause of v2 explosion:**
`max_ep=150` with no relative cut: a 50 px crossing track has nearest endpoint
≈ 25 px < 150 px → passes the cut. Beam-parallel crossing tracks dominate.

**Fix — relative endpoint cut (`max_ep_frac`):**
Two-component endpoint cut:
- Absolute: `ep < max_ep` (150 px)
- Relative: `ep < max_ep_frac × track_length` (0.5)

A genuine vertex track starts at the vertex → ep ≈ 0 px → always passes.
A crossing track: ep ≈ length/2 → relative cut rejects it.

- v3 result (+ `max_ep_frac=0.5`): **1,754,298 raw → 221,278 merged** ✓

**Spatial distribution map** (`scripts/vertex_map.py`):
![Vertex spatial map](docs/vertex_map.png)

The 45×45 FOV grid structure is visible. Bright clusters mark higher beam exposure areas.

---

## 2026-05-10 — Visual inspection; angular spread filter; run traceability; v4 run

### Visual inspection and teacher data (crop tool)

Built `scripts/crop_vertices.py` — 3-panel strip crops per vertex:
**RAW** (min projection across all z-slices, contrast-stretched) |
**FOG-REMOVED** | **BINARY**.

Min projection: dark tracks accumulate regardless of depth → shows all tracks in view.
Edge tick marks + 1 px centre dot mark the computed vertex position.

Inspected 30 crops from v3 (`n_tracks 5–12, n_slices ≥ 20, seed=7`):

| Category | Count | Crop indices |
|---|---|---|
| Emulsion artifact (crack / blob) | 7 | 003, 007, 011, 013, 025, 026, 030 |
| Good teacher (real particle tracks) | 23 | — |
| **Reaction vertex candidates** | **5** | **004, 017, 021, 023, 027** |

**Key finding**: high `n_slices` does NOT guarantee genuine vertices.
Emulsion artifacts (cracks, large blobs) persist across ALL slices → high `n_slices`.

**Event types confirmed:**

✓ **True reaction vertex** — multiple thin tracks radiating from a point at varied angles.
Seen reliably at n_tracks ≈ 8+. Large angular spread.

![True star vertex example](docs/n08_05_V00001395_n8_sl26.png)

△ **Track crossing** (false positive, minor) — long beam-parallel tracks crossing.
Dominant at n_tracks = 3–4. Largely suppressed by `max_ep_frac`.

✗ **Emulsion artifact fake** (false positive, major at n_tracks ≥ 15) — large crack or
blob survives `noise_amax=100 px²` cutoff. Its edges are detected by Hough as
near-parallel lines → fake high-multiplicity vertex with small angular spread.

![Heavy-particle fake vertex example](docs/n16_07_V00000437_n28_sl28.png)

Examples: `n11_01_V00000670_n15_sl25.png` (two thick tracks),
`n16_07_V00000437_n28_sl28.png` (thick track with kink),
`n16_08_V00001222_n24_sl29.png` (thick curved track).

### Angular spread filter

Implemented `min_angle_spread` in `find_vertices()`.
Uses doubled-angle circular statistics for line directions in [0°, 180°):
maps θ → exp(2iθ), computes mean resultant length R,
spread = arccos(R) / 2.

- n=34 artifact vertex: `angle_spread = 14.8°` → removed by threshold ≥ 15°.
- Genuine reaction vertex: large spread (tracks point in many directions).
- Set `--min-angle-spread 20.0` for KEKCC runs.

**Preprocessing fix needed (not yet done):**
Root cause of artifact fakes: `noise_amax=100 px²` only removes blobs ≤ 100 px².
Large artifacts (cracks, area >> 1000 px²) pass through unchanged → Hough detects edges.
Fix: add `noise_amax_upper` to `preprocess()` (e.g. 5000 px²) to remove large blobs.
Requires full re-run of `e07analyze` on KEKCC.

### Run traceability system

Added `e07fullscan/utils/run_info.py`.
Every output now carries:

| Field | Content |
|---|---|
| `run_id` | `YYYYMMDD_HHMMSS_<git_hash>` — unique per invocation |
| `script` | Script filename |
| `timestamp` | ISO-8601 datetime |
| `python` | Python version |
| `params` | All CLI arguments |

Stored as `<stem>_run.json` sidecar (parquet) or `run_params.json` (image dir),
and embedded in PyArrow schema metadata (`run_meta` key).

Read back:
```python
import json, pyarrow.parquet as pq
meta = json.loads(
    pq.read_table("results/vertices.parquet")
    .schema.metadata[b"run_meta"]
)
print(meta["run_id"])   # e.g. 20260510_165200_b0ec81f
print(meta["params"])
```

Scripts updated: `find_vertices.py`, `merge_vertices.py`,
`crop_vertices.py`, `vertex_map.py`.

### v4 vertex run (min_angle_spread=20°)

KEKCC array job 74625453 — 135 jobs, all DONE.
Output: `results/vertex_chunks_v4/` → `results/vertices_merged_v4.parquet`.

| n_tracks_max ≥ | v3 (spread=0°) | v4 (spread≥20°) | reduction |
|---|---|---|---|
| all | 221,278 | 207,259 | −6% |
| 5 | 127,178 | 102,178 | −20% |
| 8 | 13,180 | 8,542 | −35% |
| 10 | 4,639 | 2,143 | −54% |
| 15 | 987 | 337 | −66% |
| 20 | 215 | 91 | −58% |

Filter is most aggressive at high n_tracks_max, as expected
(artifact fakes have small angular spread).

---

## 2026-05-10 — v4 crops inspection; specials_x20 teacher events; integration tests

### v3 vs v4 crop comparison

Generated 30 crops from both v3 (`results/vertex_crops_teacher/`) and
v4 (`results/vertex_crops_v4/`) with identical parameters
(`n_tracks 5–12, n_slices≥20, seed=7`).

Because the underlying parquet files differ (v4 has 207k vs v3 221k merged),
the same random seed draws different vertices.
Qualitative comparison: v4 crops had noticeably fewer large-blob artifacts;
the high-n fake vertices with tightly clustered parallel lines were reduced.

Discussion: `n_slices` was previously thought to be a reliability metric
("more z-slices = more real"), but visual inspection shows emulsion cracks
persist across ALL slices → high `n_slices` is not a purity guarantee.

### specials_x20 teacher events

User provided 13 confirmed double-hypernuclei (or candidate) events at
`/gpfs/group/had/sks/Users/shuhei/work/specials_x20/`:

```
D005, D013, IBUKI, IRRAWADY, KISO, MINO, NAGARA,
T004, T004_3body, T004_center,
T011, T011_100, T011_200
```

Image format: plain PNG files (`0000.png`, `0001.png`, …) + `image.json`.
JSON format is identical to SPNG format except `Path` is a plain filename
rather than `file.spng&offset&length`.

`SpngReader` was extended to detect the format from the presence of `&` in
the Path field (`length=-1` sentinel for plain PNGs).

Pixel scale from `AffineP2S[0]`: 0.00028889 mm/px = **0.289 μm/px** —
identical to fullscan. Microscope settings confirmed compatible.

Z-spacing: ~3 μm/slice (vs ~1.5 μm/slice in fullscan) — factor 2 difference,
but `zpj_half=4` still gives ±12 μm range which is sufficient.

**Pipeline results on specials (all slices, min_angle_spread=0):**

| Event | Tracks | Best n | Spread |
|---|---|---|---|
| IBUKI | 39,563 | 10 | 31.9° |
| NAGARA | 61,711 | 9 | 23.2° |
| MINO | 39,858 | 18 | 30.2° |
| KISO | 38,256 | 11 | 42.4° |
| IRRAWADY | 33,943 | 10 | 38.7° |
| D005 | 97,737 | 13 | 35.5° |
| D013 | 91,253 | 12 | **13.4°** |
| T004 | 141,982 | 10 | **18.0°** |
| T011 | 26,202 | 10 | **8.2°** |

**Key finding**: D013, T004, T011 have angular spread < 20° at their
best vertex. This means the v4 `min_angle_spread=20°` production filter
would reject their primary vertex candidate.

Discussion: This does not necessarily mean the filter is wrong.
Possible explanations:
1. The "best n" vertex found is NOT the actual reaction vertex —
   could be a different feature. The true vertex may have larger spread.
2. These events genuinely have low spread (e.g. forward-boosted topology).
3. The vertex-finding algorithm is reconstructing only part of the star.

Decision: integration tests use `min_angle_spread=0` to validate the
pipeline independently of the production filter. The filter setting
is a separate optimization problem that requires ground-truth vertex positions.

**Vertex positions are NOT at image centre** (dist_center = 229–981 px).
The specials are NOT centred on the vertex; the vertex is somewhere in the
2048×2048 FOV. Cannot use "near centre" as a pass criterion in tests.

### Integration test suite (`tests/test_specials.py`)

Added `tests/test_specials.py` with two `@pytest.mark.slow` test types:

1. `test_special_reader_loads` — all 13 events, loads first/last slice,
   checks shape. Verifies reader extension works for plain PNG format.

2. `test_special_vertex_detected` — runs full track finding + vertex finding
   on each event, asserts `n_tracks_max >= 5` somewhere in the image.
   Parameters: `min_angle_spread=0, beam_angle_cut=0` (conservative, format-agnostic).

Slow tests skip by default (`pytest`); run explicitly with `pytest -m slow`.
Conftest: `tests/conftest.py` implements this via `pytest_collection_modifyitems`.
Marker registered in `pyproject.toml`.

Tested: `test_special_reader_loads` → 13/13 PASSED (3s).
`test_special_vertex_detected[IBUKI]`, `[T011]`, `[T011_100]`, `[T011_200]` → PASSED.

---

## Open Questions / Next Steps

- [ ] **Ground truth positions**: use `scripts/click_vertex.py` to record
      true reaction vertex (x,y) for each specials event → `tests/specials_gt.json`.
      Then add position-based integration tests.
- [ ] **Root cause of vertex miss**: pipeline finds 2-track crossings instead
      of the true reaction vertex in most specials events. Hypotheses:
      (1) high track density (~660/slice vs ~120 fullscan) → spurious high-n
      vertices dominate; (2) true vertex tracks have specific properties not
      matching current quality cuts; (3) geometric intersection bias.
- [ ] **Preprocessing fix**: add `noise_amax_upper` to `preprocess()`;
      requires full re-run of `e07analyze` on KEKCC.
- [ ] **Expand teacher data**: 5 reaction vertex candidates from 30 crops is too few;
      inspect 100–200 crops from `vertices_merged_v4.parquet`.
- [ ] **Parameter reconsideration**: after expanding teacher data, revisit all
      vertex-finding thresholds using confirmed genuine events.
- [ ] **Track re-analysis**: re-run `e07analyze` with `px_scale=0.29` to fix
      `grain_density` (currently 10× too low).
- [ ] **Grain density as PID**: once corrected, distinguishes α / slow proton / MIP.
- [ ] **Two-vertex search**: find vertex pairs in same view 30–167 px apart
      → ΛΛ secondary decay topology.
- [ ] **width_px filter**: `mean(width_px) < threshold` at vertex to reject
      thick heavy-track fakes.
- [ ] **Dip angle improvement**: only ~2% of tracks span >1 slice currently.

---

## 2026-05-11 — Vertex candidate maps; ground truth strategy; indentation fix

### Vertex candidate map generation

Generated all-candidates overlay maps for IBUKI, D013, T004, T011
(`results/specials_crops/*_all_vertices_map.png`):
- Green circles: vertices with spread ≥ 20°, radius ∝ n_tracks
- Yellow circles: vertices with spread < 20°
- n ≥ 7 vertices labelled with n value
- Background: min projection over all z-slices (all tracks visible)

**Key finding (critical)**: Visual inspection showed that ALL of the
pipeline's top-candidate vertices (highest n_tracks near image centre)
were **2-track crossings** — not reaction vertices. The true reaction
vertex was NOT the highest-n candidate.

T011 was the only event where a pipeline candidate (at pixel (994,983),
dist_center=50px) was close to the true vertex — described as "mettya oshii"
(very close but not exact).

This means the current pipeline cannot reliably identify the true reaction
vertex in specials events, even with centre-restricted search. Root cause
is not yet clear — candidates include high track density creating spurious
high-n intersections, and the geometric intersection algorithm not favouring
the true star topology.

### Ground truth collection strategy

Decided to collect true reaction vertex pixel positions directly from the
expert (user), using a dedicated interactive tool rather than inferring
from the pipeline output.

Added `scripts/click_vertex.py`:
- Displays min projection (all z-slices) of a specials event
- User clicks on the true reaction vertex
- Pixel coordinates (x, y) printed to terminal
- Supports both single PNG and directory (auto min-projection)

Next step: user identifies true vertex positions for each event →
record in `tests/specials_gt.json` → add position-based integration tests
that assert the pipeline finds a vertex within tolerance of the known position.

### Code quality: indentation rule fix

CLAUDE.md specifies 2-space indentation. Audit found that 13 source files
in `e07fullscan/` and `tests/` were using 4-space indentation.
All converted to 2-space. All 48 non-slow tests pass after conversion.

Affected files: `clustering/__init__.py`, `clustering/_cluster.py`,
`clustering/_vertex.py`, `merge/cli.py`, `server/__init__.py`,
`server/app.py`, `server/cli.py`, `server/results.py`,
`tracking/_finder.py`, `tracking/_track.py`,
`tests/test_clustering.py`, `tests/test_linking.py`,
`tests/test_results_viewer.py`.
