# e07fullscan

Analysis toolkit for E07 nuclear emulsion full-scan data.  
Designed for double-hypernuclei (ΛΛ) search via track finding, vertex
detection, and large-scale batch processing on KEKCC.

## Setup

```bash
# Analysis library only
pip install -e .

# With web viewer
pip install -e ".[server]"

# Development environment (tests and lint)
pip install -e ".[dev]"
```

Dependencies: numpy, scipy, opencv-python, matplotlib, PyYAML,
pandas, pyarrow  
Additional dependency for web viewer: flask

## Package Structure

```
e07fullscan/
├── io/
│   └── image_reader.py   # SPNG format reader
├── tracking/             # Track finding
│   ├── _track.py         # Track dataclass
│   └── _finder.py        # preprocess(), find_tracks()
├── analyze/              # Batch analysis CLI
│   └── cli.py            # e07analyze entry point
├── merge/                # Result merge CLI
│   └── cli.py            # e07merge entry point
├── clustering/           # Post-processing
│   ├── _cluster.py       # cluster_tracks(), cluster_df()
│   ├── _link.py          # link_tracks(), best_per_track(), add_dip_angles()
│   └── _vertex.py        # find_vertices(), merge_vertex_slices()
├── server/               # Web viewer (requires flask)
│   ├── app.py
│   ├── results.py
│   └── __main__.py
└── utils/
```

## Agent Coordination

When multiple coding agents are active, use `discussion.md` as an append-only
coordination log and `discussion_ja.md` as its Japanese counterpart. Record
the current task, assumptions, files being edited, and open questions before
making overlapping changes.

`AGENTS.md` and `CLAUDE.md` now make this coordination mandatory: agents must
check both discussion logs before repository work, before editing shared files,
and before final reporting. Job launches, generated outputs, and script changes
should be announced there with intended inputs, outputs, and file ownership.

## SPNG Format

A proprietary format used in E07 full-scan data. Each view (field of view)
consists of a JSON/SPNG file pair.

- **JSON file**: Metadata (image size, number of slices, XYZ coordinates per
  slice, affine transformation coefficients, etc.)
- **SPNG file**: Binary container holding concatenated PNG blobs.  
  `Images[].Path` in the JSON has the form
  `filename.spng&byte_offset&byte_length`, specifying each image's location.

The scanner metadata lists `x = y = 0.003 mm/px`, but the confirmed
pixel scale from scan geometry is **0.29 μm/px** (FOV ≈ 594 μm).
Set `px_scale_um: 0.29` in `config/default.yaml` (current default).

## SPNG Image Reader

```python
from e07fullscan.io import load_spng

reader = load_spng("path/to/scan.json")
```

### Attributes

| Attribute | Type | Description |
|---|---|---|
| `reader.image_type` | `ImageType` | `depth`, `height`, `width` |
| `reader.affine_p2s` | `list[float]` | Affine coefficients pixel→stage (6 elements) |
| `reader.datetime` | `str` | Acquisition datetime string |
| `reader.entries` | `list[ImageEntry]` | SPNG location and XYZ coordinates per slice |

### Reading Images

```python
len(reader)              # Number of slices
reader.z_positions()     # Z coordinate of each slice (ndarray, float64)

img   = reader.read(0)         # Grayscale image (H×W, uint8)
raw   = reader.read_raw(0)     # Raw PNG bytes (no decode)
stack = reader.read_stack()    # All slices as a stack (N×H×W, uint8)

reader[0]           # Equivalent to read()
for img in reader:  # Iteration supported
    ...
```

## Tracking API

Find track segments in a single Z-slice and return them in stage coordinates.

```python
from e07fullscan.io import load_spng
from e07fullscan.tracking import find_tracks

reader = load_spng("path/to/scan.json")
tracks = find_tracks(reader, idx=10, view_id="path/to/scan.json",
                     px_scale_um=3.0)
```

`find_tracks` applies: Z-projection → fog removal → Otsu threshold →
noise removal → HoughLinesP.  Stack pre-loading (`_stack=`) avoids
repeated file I/O when iterating over all slices.

### Track Fields

| Field | Type | Description |
|---|---|---|
| `x1, y1, x2, y2` | float | Start/end points in stage coordinates |
| `z` | float | Stage Z of the slice |
| `px1, py1, px2, py2` | int | Start/end points in pixel coordinates |
| `length_px` | float | Segment length in pixels |
| `angle_deg` | float | Line angle 0–180° |
| `view_id` | str | Source JSON path |
| `n_grains` | int | Grain blob count within `grain_radius` px of segment |
| `width_px` | float | Transverse spread of nearby grain centroids (px) |
| `mean_intens` | float | Mean fog-removed intensity along the segment |
| `grain_density` | float | Grains per 100 μm (when `px_scale_um > 0`) |
| `px_scale_um` | float | Pixel scale in μm/px (from scanner metadata) |
| `view_x_mm` | float | Stage X of this FOV (mm) |
| `view_y_mm` | float | Stage Y of this FOV (mm) |

## Batch Analysis

```bash
# Single process
python -m e07fullscan.analyze /data/scan_dir -o tracks.parquet -v

# Parallel chunk (KEKCC array job)
python -m e07fullscan.analyze /data/scan_dir \
  --chunk-id 0 --chunk-total 135 \
  -o results/chunk_0001.parquet -j 1 -v

# Custom config
python -m e07fullscan.analyze /data/scan_dir \
  --config config/default.yaml -o tracks.parquet
```

### Output Columns

| Column | Description |
|---|---|
| `view_id` | Source JSON path |
| `slice_idx` | Slice index within the view |
| `px1, py1, px2, py2` | Track endpoints in pixels |
| `length_px` | Track length (px) |
| `angle_deg` | Angle 0–180° |
| `mean_intens` | Fog-removed intensity along track |
| `grain_density` | Grains/100 μm (0 if `px_scale_um` unknown) |
| `px_scale_um` | Pixel scale (μm/px) |
| `view_x_mm, view_y_mm` | FOV stage position (mm) |

## Analysis Parameters (`config/default.yaml`)

Key parameters for track quality and physics sensitivity:

| Parameter | Default | Description |
|---|---|---|
| `hough_thr` | 35 | Hough accumulator threshold (higher → fewer noise tracks) |
| `hough_ml` | 30 | Minimum line length (px) = 8.7 μm at 0.29 μm/px |
| `hough_mg` | 5 | Maximum line gap (px) = 1.5 μm |
| `px_scale_um` | 0.29 | Pixel scale confirmed from scan geometry (μm/px) |
| `zpj_half` | 4 | Z-projection half-range (slices) |
| `fog_ksize` | 51 | Gaussian kernel size for fog removal |
| `grain_radius` | 10 | Grain association radius (px) |
| `noise_amax_upper` | 0 | Remove blobs larger than this (px²); 0=disabled |

## KEKCC Batch Pipeline

Full pipeline for 2025-view scan on KEKCC (LSF):

```bash
# 1. Track finding (135 array jobs, ~9 min total)
python scripts/submit_kekcc.py          # reads config/kekcc.yaml

# 2. Monitor progress
python scripts/monitor.py --job-name e07full \
    --log-dir logs/kekcc --out-dir results --total 2025
# Compact display for small windows:
python scripts/monitor.py --job-name e07full --compact

# 3. Merge track chunks
python scripts/merge_chunks.py \
    --input results --output results/merged.parquet

# 4. Vertex finding (135 array jobs, ~30 s total)
python scripts/submit_vertex_kekcc.py

# 5. Merge vertex chunks
python scripts/merge_chunks.py \
    --input results/vertex_chunks \
    --pattern 'vertex_*.parquet' \
    --output results/vertices.parquet

# 6. Cross-slice merge + image crop extraction
python scripts/merge_vertices.py \
    --input  results/vertices.parquet \
    --output results/vertices_merged.parquet \
    --crops  results/vertex_crops \
    --min-slices 3 --min-tracks 8
```

### `config/kekcc.yaml`

```yaml
job:
  name:     e07full
  queue:    s          # priority 120 — fastest on KEKCC
  n_cores:  2
  mem_mb:   4000
  walltime: "01:00"
  n_jobs:   135        # 2025/135 = 15 views/job (~9 min)

data:
  input:       /gpfs/.../IMAGE00_AREA00
  output_dir:  results
  total_views: 2025

analysis:
  config:  config/default.yaml
  workers: 1           # keep 1 to avoid TERM_MEMLIMIT
```

## Vertex Finding

Finds nuclear interaction vertex candidates from track intersections.

### Algorithm

1. Per `(view_id, slice_idx)`, select quality tracks
   (`mean_intens ≥ 12`, `length_px ≥ 100`)
2. Optionally remove beam-parallel tracks (`beam_angle_cut = 15°`):
   exclude tracks with `angle_deg < 15°` or `> 165°`
   (beam direction is horizontal; these tracks inflate false-vertex counts)
3. Compute all pairwise 2D line intersections (vectorised with numpy)
4. Filter by:
   - Perpendicular distance to vertex < `max_impact` (30 px = 90 μm)
   - **Nearest endpoint** of each track < `max_ep` (100 px = 300 μm)
     — this rejects pass-through crossings, keeping only tracks that
     originate or terminate near the vertex
5. Grid-cluster intersection points (eps = 25 px)
6. Output clusters with ≥ 3 contributing tracks

### Cross-slice Merge

The same physical vertex appears in multiple adjacent `slice_idx` due to
Z-projection overlap.  `merge_vertex_slices()` merges candidates within
50 px XY proximity across all slices of a view:

| Output column | Description |
|---|---|
| `vx_px, vy_px` | n_tracks-weighted mean position |
| `n_tracks_max` | Max track count across contributing slices |
| `n_slices` | Number of distinct slices that voted |
| `z_mean, z_min, z_max` | Depth range of the vertex |
| `view_x_mm, view_y_mm` | FOV stage position (mm) |

### Python API

```python
import pandas as pd
from e07fullscan.clustering import find_vertices, merge_vertex_slices

df   = pd.read_parquet("results/merged.parquet")
# beam_angle_cut removes tracks with angle_deg < 15° or > 165°
vdf  = find_vertices(df, min_tracks=3, max_ep=100.0, min_intens=12.0,
                     beam_angle_cut=15.0)
mdf  = merge_vertex_slices(vdf, eps_xy=50.0, min_slices=3)

# High-multiplicity star candidates
stars = mdf[mdf['n_tracks_max'] >= 8].sort_values('n_tracks_max',
                                                    ascending=False)
```

### find_vertices Parameters

| Parameter | Default | Description |
|---|---|---|
| `min_tracks` | 3 | Min tracks to form a vertex |
| `max_impact` | 30 px | Max perpendicular distance to vertex |
| `max_ep` | 150 px | Max nearest-endpoint distance (43 μm) |
| `min_intens` | 10.0 | Quality cut on mean_intens (efficiency-first) |
| `min_len_px` | 50 px | Quality cut on length_px (= 14.5 μm; catches α tracks) |
| `beam_angle_cut` | 0° | Exclude tracks with angle_deg < cut or > 180°−cut |

**Beam track note**: ~22% of tracks have `angle_deg < 15°` or `> 165°`
(beam direction).  Setting `beam_angle_cut=15.0` reduces false vertices
by ~13% in high-quality views while retaining top star candidates.

### n_slices Quality Cut

`n_slices` measures how many z-projection slices voted for a merged vertex
(higher = more reliable).  Recommended thresholds:

| n_slices ≥ | Fraction retained | Use case |
|---|---|---|
| 3 | 100% | All candidates |
| 5 | 36% | Moderate purity |
| 8 | 13% | High-multiplicity stars only |

### Image Crop Extraction

`scripts/merge_vertices.py --crops <dir>` saves a PNG crop centred on
each vertex candidate.  The green circle marks the vertex; the label
shows `n=<n_tracks_max> sl=<n_slices>`.

### Spatial Distribution Map

```bash
python scripts/vertex_map.py \
    --input  results/vertices_merged.parquet \
    --output results/vertex_map.png \
    --min-tracks 5 --min-slices 3
```

Generates two panels: scatter plot coloured by `n_tracks_max` and a
log-scale density map per FOV.

### Vertex crop tool (`scripts/crop_vertices.py`)

Crops raw SPNG images around vertex positions for visual inspection.
Each output PNG is a 3-panel strip: **RAW** (min projection, contrast-stretched)
| **FOG-REMOVED** | **BINARY**, with edge tick marks and a 1 px dot at the
computed vertex centre.

```bash
python scripts/crop_vertices.py \
    --vertices   results/vertices_merged.parquet \
    --output-dir results/vertex_crops/ \
    --n-samples  30 \
    --min-tracks 5 --max-tracks 12 --min-slices 20 \
    --shuffle --seed 7 \
    --crop-size  200
```

| Option | Default | Description |
|---|---|---|
| `--crop-size` | 200 | Half-size of crop in px (total = 2×) |
| `--min-tracks` | 3 | Min `n_tracks_max` |
| `--min-slices` | 1 | Min `n_slices` |
| `--shuffle` | off | Random sample (default: top-n by n_tracks_max) |
| `--zpj-half` | 4 | Z-projection half-range for fog/binary panels |
| `--zpj-mode` | mean | Projection mode: `mean` or `max` |

## Vertex Pair Search

Finds primary + secondary vertex pairs for hypernuclear event pickup
(ΛΛ, single Λ, alpha stars). Current pipeline uses **v6 vertices**
(hough_ml=30, 237k vertices across 2025 views).

```bash
# 1. Find all candidate pairs (90-500 μm)
python scripts/find_pairs.py \
  --input  results/vertices_merged_v6.parquet \
  --output results/vertex_pairs_v6.parquet \
  --d-min 310 --d-max 1724 \
  --min-n-primary 5 --min-n-secondary 3 \
  --max-dz-mm 0.010

# 2. Require connecting track (connecting particle flight path)
python scripts/filter_pairs_by_track.py \
  --pairs  results/vertex_pairs_v6.parquet \
  --output results/vertex_pairs_v6_filtered.parquet \
  --min-n-primary 10

# 3. Generate visual crops
python scripts/crop_pairs.py \
  --pairs  results/vertex_pairs_v6_filtered.parquet \
  --output results/pair_crops_v6/ \
  --top 200 --min-n-primary 10
```

**v5/v7 note**: vertex_pairs_v5.parquet used wrong d-min=30, d-max=167
(hough_ml values accidentally substituted). v7 (from v5 vertices,
hough_ml=50) used the correct range; v6 (hough_ml=30) supersedes it.

Output columns of `find_pairs.py`:

| Column | Description |
|---|---|
| `p_vx, p_vy` | Primary vertex position (px) |
| `p_ntracks` | Max track count at primary vertex |
| `p_nslices` | Slice count at primary vertex |
| `p_z` | Depth of primary vertex (mm) |
| `s_vx, s_vy, s_ntracks, s_nslices, s_z` | Same for secondary vertex |
| `dist_px, dist_um` | XY separation (px and μm) |
| `dz_mm` | Z separation (mm) |
| `p_angle_spread` | Angular spread of primary vertex tracks (°) |
| `s_angle_spread` | Angular spread of secondary vertex tracks (°) |

`angle_spread` reflects the directional diversity of tracks: a genuine
interaction vertex typically has spread > 25°; values near 20° (the
production-cut minimum) may indicate ghost vertices.

## Cross-View ΛΛ Pair Search

When the primary vertex of a ΛΛ event falls near the boundary between two
adjacent scan views, intra-view pair finding misses it.
`scripts/find_crossview_pairs.py` handles this case by matching vertices from
different views using their physical (stage) coordinates.

```bash
# v6 pipeline (current)
python scripts/find_crossview_pairs.py \
  --vertices results/vertices_merged_v6.parquet \
  --output   results/vertex_pairs_xview_v6.parquet \
  --min-n-primary 5 --min-n-secondary 3 \
  --d-min-um 90 --d-max-um 500 --max-dz-mm 0.200

# Pre-filter before boundary-crossing filter (reduces 23M → 204k)
# Cuts: adjacent-view, p_sp≥35°, s_sp≥20°, p_nsl≥5, s_nsl≥4,
#       p_n≥8, d≤400μm (KISO passes: sp=42°>35°, n=11>8, d=152μm<400μm)

# Boundary-crossing track filter (Ξ⁻ exits primary view edge)
python scripts/filter_xview_pairs.py \
  --pairs  results/vertex_pairs_xview_v6_prefiltered.parquet \
  --chunks results/chunks_v6 \
  --output results/vertex_pairs_xview_v6_conn.parquet
```

Stage coordinates are computed using **Convention C** (x-axis mirrored):
```
stage_x = view_cx - (vx_px - 1024) × 0.00029 mm
stage_y = view_cy + (vy_px - 1024) × 0.00029 mm
```

The `max_dz_mm` default is 0.200 mm (vs 0.010 mm for intra-view) to allow
for dip angles up to ~45° at 500 μm flight distance.

**KISO result** (v6, hough_ml=30): P=(354,1204) n=11 sp=42° ↔
S=(1888,716) n=5 sp=23°, d=152 μm, dz=0.026 mm. Detected in
vertex_pairs_xview_v1_conn_ll.parquet (v5 vertices) at rank 988/2952.

## Clustering API

```python
from e07fullscan.clustering import cluster_tracks, cluster_df
from e07fullscan.clustering import link_tracks, best_per_track, add_dip_angles

# Merge duplicate Hough segments
merged = cluster_tracks(tracks, dist_eps=20.0, angle_eps=5.0)
df_merged = cluster_df(df)

# Cross-view track linking
linked = link_tracks(df_merged)
best   = best_per_track(linked)
best   = add_dip_angles(best)
```

## Monitor Script

```bash
# Full display (batch mode)
python scripts/monitor.py --job-name e07full \
    --log-dir logs/kekcc --out-dir results --total 2025

# Compact 4-line display for small tmux panes
python scripts/monitor.py --job-name e07full --compact

# Custom width
python scripts/monitor.py --job-name e07full --compact --width 50

# Local single-process mode
python scripts/monitor.py --log analyze.log --output out.parquet
```

## Web Viewer

```bash
python -m e07fullscan.server.app --data /path/to/scan_dir --port 8000
# SSH tunnel for remote access:
ssh -L 8000:localhost:8000 username@login.kekcc.jp
```

| URL | Description |
|---|---|
| `/view/` | Image Viewer — live pipeline, SPNG browsing |
| `/results/` | Results Viewer — stored track images |
| `/viewer3d/` | 3D Viewer — interactive track visualization |

### Processing Pipeline

| # | Step | Default Parameters |
|---|---|---|
| 1 | Z-Projection | half=4 (9 slices) |
| 2 | Fog Removal | ksize=51 |
| 3 | Otsu Threshold | — |
| 4 | Noise Removal | area_max=100, compactness=50 |
| 5 | Hough Lines | minLen=30 px, maxGap=5, threshold=35 |
| 6 | Tracks Only | — |

![Pipeline: all 6 processing steps](docs/pipeline.png)

## Run Traceability

Every output file can be traced back to the exact parameters and code
version that produced it.  The mechanism is provided by
`e07fullscan/utils/run_info.py`.

### What is recorded

| Field | Content |
|---|---|
| `run_id` | `YYYYMMDD_HHMMSS_<git_hash>` — unique per invocation |
| `script` | Script filename |
| `timestamp` | ISO-8601 datetime |
| `python` | Python version |
| `params` | All CLI arguments as a dict |

### Where it is stored

| Output type | Sidecar location |
|---|---|
| `*.parquet` | `<stem>_run.json` next to the parquet file |
| Image directory | `run_params.json` inside the directory |
| PNG file | `<stem>_run.json` next to the PNG |

Run metadata is also embedded in parquet files via PyArrow schema
metadata (`run_meta` key), so the information travels with the data
even if the sidecar is lost.

### Reading back from a parquet file

```python
import json, pyarrow.parquet as pq
tbl  = pq.read_table("results/vertices.parquet")
meta = json.loads(tbl.schema.metadata[b"run_meta"])
print(meta["run_id"])   # e.g. 20260510_165200_abc1234
print(meta["params"])   # all CLI args
```

### API

```python
from e07fullscan.utils import (
    make_run_id,            # "20260510_165200_abc1234"
    build_run_meta,         # {run_id, script, timestamp, python, params}
    save_run_json,          # write <stem>_run.json sidecar
    save_parquet_with_meta, # to_parquet + embed run_meta in schema
)
```

## Analysis Notes

Physics findings, parameter decisions, and event-type observations are recorded in
[ANALYSIS.md](ANALYSIS.md).

## Ground Truth Collection

```bash
# Click on reaction vertex to record pixel coordinates
python scripts/click_vertex.py /path/to/specials_x20/T011/

# Single slice
python scripts/click_vertex.py /path/to/specials_x20/T011/0000.png
```

When a directory is given, a min projection over all z-slices is displayed
(all tracks visible simultaneously).  Click on the reaction vertex; the pixel
coordinates (x, y) are printed to the terminal.  Multiple clicks are
supported — a summary is printed on close.

## Tests

```bash
pytest              # fast tests only (slow tests skipped)
pytest -m slow      # confirmed-event integration tests (specials_x20)
pytest -v           # verbose output
```

Slow tests (`pytest -m slow`) run the full pipeline on the 13 confirmed
double-hypernuclei events in `specials_x20` and assert that a multi-track
vertex is detected in each.
