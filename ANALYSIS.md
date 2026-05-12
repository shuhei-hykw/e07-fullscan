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

- [x] **Ground truth positions**: recorded in `tests/specials_gt.json` (2026-05-12).
- [x] **Root cause of vertex miss**: grid-hash clustering bug — fixed with KDTree
      union-find (2026-05-13). All 9 specials events now PASS position test.
- [x] **v5 vertex run on KEKCC**: complete (2026-05-13). New results in
      `results/vertices_merged_v5.parquet`. See 2026-05-13 entry below.
- [ ] **2D analysis investigation**: per-slice analysis with ±2–4 slice
      superimposition + contrast improvement (CLAHE). Discussed 2026-05-13;
      keep current method but prototype the 2D approach for comparison.
- [ ] **Preprocessing fix**: add `noise_amax_upper` to `preprocess()`;
      requires full re-run of `e07analyze` on KEKCC.
- [ ] **Expand teacher data**: 5 reaction vertex candidates from 30 crops is too few;
      inspect 100–200 crops from updated vertex results.
- [ ] **Track re-analysis**: re-run `e07analyze` with `px_scale=0.29` to fix
      `grain_density` (currently 10× too low).
- [ ] **Grain density as PID**: once corrected, distinguishes α / slow proton / MIP.
- [x] **Two-vertex search**: `find_vertex_pairs()` + `scripts/find_pairs.py`
      implemented (2026-05-13). v5 run: 5,059 candidates (p_ntracks≥10) in
      1,153 views. See 2026-05-13 entry for details.
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

## 2026-05-12 — Ground truth click session; caveats

Ran `scripts/click_vertex.py` interactively on specials_x20 events.
Expert (user) clicked on the true reaction vertex for each event.
Results saved as JSON files under `results/specials_vertex_click/`.

| File | Image | Clicks saved |
|------|-------|-------------|
| T011_0025.json | T011/0025.png | 2 (clicks 1,3 of 3) |
| IBUKI_0010.json | IBUKI/0010.png | 4 (all) |
| D005_0100.json | D005/0100.png | 2 (all) |
| D013_0100.json | D013/0100.png | 2 (all) |
| IRRAWADY_0011.json | IRRAWADY/0011.png | 3 (all) |
| KISO_0010.json | KISO/0010.png | 5 (all) |
| MINO_0028.json | MINO/0028.png | 2 (all) |
| NAGARA_0012.json | NAGARA/0012.png | 3 (all) |
| T004_0100.json | T004/0100.png | 1 (all) |

**Important caveats (user note):**
1. Click positions are approximate, not pixel-exact. Do not treat these
   coordinates as ground truth with sub-pixel accuracy.
2. Candidates far from the image centre may look vertex-like but are
   confirmed NOT to be double-track (reaction) vertices. Distance from
   centre is a useful negative signal.

Next step: use these approximate positions as loose ground truth to
evaluate pipeline candidates (e.g. within 50–100 px tolerance), keeping
the caveats above in mind when setting acceptance thresholds.

### Ground truth JSON and position+Z test

Saved `tests/specials_gt.json` with:
- XY pixel position per event (averaged over near-center clicks)
- Z coordinate (μm) from `reader.z_positions()[slice_idx]` using the
  slice number in the click filename (e.g. T011/0025.png → slice 25)
- Tolerance: `tolerance_xy_px=200`, `tolerance_z_um=30`

Key observation: all ground-truth Z values are within ±0.4 μm of 0,
confirming that the specials scans are centered on the vertex in Z.

Added `test_special_vertex_position` to `tests/test_specials.py`:
- Runs full pipeline including `merge_vertex_slices`
- Checks if any merged candidate is within 200 px XY AND 30 μm Z
  of the ground-truth position
- Currently expected to fail for most events (only D005 passes):
  the pipeline finds 2-track crossings rather than the true star vertex

Pipeline result vs ground truth (200 px XY tolerance):

| Event | True vertex | Pipeline's nearest candidate | dist XY |
|-------|-------------|------------------------------|---------|
| D005 | (1020,1023) | (1024,1021) n=12 | **3px** ✓ |
| KISO | (1096,1028) | (970,1144) n=9 | 171px (candidate within 200px?) |
| T004 | (1023,1038) | (881,992) n=11 | 149px |
| T011 | (992,984) | (813,1113) n=10 | 221px |
| NAGARA | (1020,1021) | (1151,1225) n=7 | 243px |
| IRRAWADY | (1010,1018) | (826,861) n=9 | 241px |
| D013 | (998,990) | (833,1321) n=10 | 370px |
| MINO | (1016,1018) | (725,829) n=11 | 348px |
| IBUKI | (982,968) | (936,1385) n=10 | 419px |

The `test_special_vertex_position` tests document the gap between current
pipeline capability and ground truth — passing them is the improvement target.

Updated `scripts/click_vertex.py` to record Z information (slice index and
z_um from `reader.z_positions()`) when a specific slice file is given.

---

## 2026-05-13 — KDTree clustering fix; pipeline status script; Japanese diary

### Root cause identified: grid-hash clustering bug

The previous intersection clustering in `_vertices_in_group` assigned each
point to a 25 px grid cell by hashing `gx * 100003 + gy`. Two points
straddling a cell boundary could be < 25 px apart yet land in different
clusters. For a star vertex with n tracks producing n(n-1)/2 intersection
points scattered over ~25–50 px, the grid split them into sub-clusters with
n_tracks < 3 → rejected by `min_tracks`. This silently missed the true vertex.

**Fix**: replaced grid hash with `cKDTree.query_pairs(eps_px)` + union-find
(path-compressed). All points within eps_px are guaranteed to merge.

### Verification on all 9 specials events (production cuts, KDTree fix)

Explicit post-fix run confirmed 9/9 PASS:

| Event | n | dist XY | Z |
|-------|---|---------|---|
| T011 | 9 | 2 px | −0.1 μm |
| IBUKI | 14 | 3 px | 0.2 μm |
| D005 | 12 | 5 px | 0.4 μm |
| MINO | 10 | 22 px | 0.0 μm |
| NAGARA | 7 | 25 px | −0.1 μm |
| IRRAWADY | 7 | 158 px | −0.3 μm |
| KISO | 9 | 171 px | −0.1 μm |
| T004 | 11 | 178 px | 0.2 μm |
| D013 | 12 | 185 px | −0.1 μm |

All within 200 px XY and 30 μm Z tolerance, all n ≥ 5.
`test_special_vertex_position` confirmed passing for all 9 events.

### Full slow test suite result (2026-05-13)

`pytest -m slow tests/test_specials.py` — **35/35 passed** (1 h 38 min):
- `test_special_vertex_detected`  13/13 ✓
- `test_special_vertex_position`   9/9  ✓  (new; ground-truth position test)
- `test_special_reader_loads`     13/13 ✓

### Pipeline status script

Added `scripts/status.py` (zero arguments):
```
python scripts/status.py
```
Shows track chunk count, merged parquet row count, vertex chunk progress,
and KEKCC running jobs in one compact view. Replaces multi-flag monitor.py
for quick status checks.

### Japanese development diary

Added `ANALYSIS_ja.md` — Japanese mirror of this file, updated in sync.
`CLAUDE.md` updated to require keeping both files current.

---

## 2026-05-13 — v5 full-scan vertex run; ΛΛ vertex pair search

### v5 KEKCC run (KDTree fix applied)

Re-ran vertex finding for all 135 chunks with the KDTree union-find fix.
Parameters identical to v4 (`min_tracks=3`, `min_angle_spread=20°`,
`beam_angle_cut=15°`, `eps=25 px`, `max_ep=150 px`).

| Metric | v4 | v5 | Change |
|--------|-----|-----|--------|
| Raw candidates | 1,091,300 | 1,091,300 | same |
| Merged vertices (min_slices=2) | 207,259 | 212,777 | +2.7% |
| n_tracks_max ≥ 5 | 102,178 | 114,089 | +11.7% |
| n_tracks_max ≥ 10 | 2,143 | 3,933 | **+83.5%** |

The dramatic improvement in high-multiplicity vertices confirms the bug fix:
the old grid-hash was splitting star vertices' intersection clusters, while
KDTree correctly merges all intersections within `eps_px`. The effect is
largest for high-n events precisely because they had more intersections to
be split across grid boundaries.

Vertex map: `results/vertex_map_v5.png` (n_tracks≥5, n_slices≥3; 102,889
candidates shown).

### Z scale discovery

Z values in `z_mean` column are in **mm** (scanner stage unit), not μm.
- z_step ≈ 0.003 mm = 3 μm per slice
- Full-scan z range: −0.259 to −0.048 mm (≈ 211 μm total emulsion thickness)
- Specials views span 0.177 mm = 177 μm per event

This matters for the dz filter in vertex pair search: threshold of 0.010 mm
(= 10 μm ≈ 3 z-steps) selects same-layer vertex pairs.

### ΛΛ topology vertex pair search

Implemented `e07fullscan.clustering.find_vertex_pairs()` and
`scripts/find_pairs.py`.

Search criteria:
- Same view
- XY separation: 30–167 px (90–500 μm)
- Primary: n_tracks_max ≥ min_n_primary
- Secondary: n_tracks_max ≥ 3, n_slices ≥ 2
- dz < 0.010 mm (10 μm; both vertices at same emulsion depth)

v5 results (min_n_primary=5):

| n_primary cut | Pairs | Views |
|---------------|-------|-------|
| ≥ 5 | 95,353 | 2,025 |
| ≥ 8 | 14,760 | 1,901 |
| ≥ 10 | 5,059 | 1,153 |
| ≥ 15 | 1,423 | 250 |

With p_ntracks ≥ 10: 5,059 candidates in 1,153 views is a manageable
number for semi-manual scanning. The 9 confirmed ΛΛ events from specials_x20
should all appear in this list (pending cross-matching with full-scan view IDs).

**Next step**: generate two-vertex crop images (both primary and secondary
visible) for the top candidates sorted by primary n_tracks_max, for manual
scanning to identify true ΛΛ events.
