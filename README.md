# e07fullscan

Analysis toolkit for E07 emulsion full-scan data.

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
├── clustering/           # Post-processing: merge duplicate Hough segments
│   └── _cluster.py       # cluster_tracks(), cluster_df()
├── server/               # Web viewer (requires flask)
│   ├── app.py
│   ├── results.py        # Results viewer backend
│   └── __main__.py
└── utils/                # Common utilities (under development)
```

## SPNG Format

A proprietary format used in E07 full-scan data. Each view (field of view)
consists of a JSON/SPNG file pair.

- **JSON file**: Metadata (image size, number of slices, XYZ coordinates per
  slice, affine transformation coefficients, etc.)
- **SPNG file**: Binary container holding concatenated PNG blobs.  
  `Images[].Path` in the JSON has the form
  `filename.spng&byte_offset&byte_length`, specifying each image's location.

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
tracks = find_tracks(reader, idx=10, view_id="path/to/scan.json")

for t in tracks:
    print(t.x1, t.y1, t.x2, t.y2, t.z)
```

`find_tracks` applies the full preprocessing pipeline (Z-projection → fog
removal → Otsu threshold → noise removal) before running HoughLinesP.
The same parameters as the web viewer are accepted as keyword arguments.

### Track Fields

| Field | Type | Description |
|---|---|---|
| `x1, y1, x2, y2` | `float` | Start/end points in stage coordinates |
| `z` | `float` | Stage Z of the slice (`reader.entries[idx].z`) |
| `px1, py1, px2, py2` | `int` | Start/end points in pixel coordinates |
| `length_px` | `float` | Segment length in pixels |
| `angle_deg` | `float` | Line angle 0–180° |
| `view_id` | `str` | Source JSON path (set by caller) |
| `n_grains` | `int` | Number of grain blobs within `grain_radius` px of the segment |
| `width_px` | `float` | Transverse spread (std dev) of nearby grain centroids (px) |
| `mean_intens` | `float` | Mean fog-removed intensity sampled along the segment |

## Batch Analysis

Run track finding over a directory tree and write results to CSV or
Parquet. For parallel KEKCC jobs, use `--chunk-id/--chunk-total` to
split the JSON file list across workers.

```bash
# Single job — CSV output
e07analyze /data/MOD108 -o tracks.csv -v

# Single job — Parquet output
e07analyze /data/MOD108 -o tracks.parquet -v

# Parallel jobs (e.g. PBS job array with 100 workers)
e07analyze /data/MOD108 \
  --chunk-id $PBS_ARRAY_INDEX --chunk-total 100 \
  -o results/chunk_${PBS_ARRAY_INDEX}.parquet

# Analyze one slice only
e07analyze /data/MOD108 --slice 10 -o tracks.parquet

# Use a custom parameter config
e07analyze /data/MOD108 --config my_params.yaml -o tracks.parquet
```

`python -m e07fullscan.analyze` works as an alias if `e07analyze` is not
on PATH.

### Output Format

| Column | Type | Description |
|---|---|---|
| `view_id` | str | Source JSON path |
| `slice_idx` | int | Slice index within the view |
| `x1, y1, x2, y2` | float | Track endpoints in stage coordinates |
| `z` | float | Stage Z of the slice |
| `px1, py1, px2, py2` | int | Track endpoints in pixel coordinates |
| `length_px` | float | Track length in pixels |
| `angle_deg` | float | Track angle 0–180° |
| `n_grains` | int | Grain blob count along the segment |
| `width_px` | float | Transverse grain spread (px) |
| `mean_intens` | float | Mean fog-removed intensity along the segment |

## Merging Results

After all parallel jobs complete, merge Parquet chunks into a single
SQLite database for interactive querying.

```bash
e07merge results/ -o tracks.db -v
```

`e07merge` creates indices on `view_id`, `z`, and `angle_deg`
automatically. Query the result with pandas or any SQLite client:

```python
import sqlite3, pandas as pd

conn = sqlite3.connect("tracks.db")
df = pd.read_sql(
    "SELECT * FROM tracks WHERE angle_deg < 5 AND length_px > 50",
    conn,
)
```

`python -m e07fullscan.merge` works as an alias if `e07merge` is not
on PATH.

## Clustering API

Merge duplicate Hough segments that represent the same physical track.
Two segments are considered duplicates when their Hough normal-form
parameters (ρ, θ) satisfy |Δρ| < `dist_eps` pixels and |Δθ| < `angle_eps`
degrees. The longest segment in each cluster is kept.

```python
from e07fullscan.clustering import cluster_tracks, cluster_df

# List[Track] → List[Track] (one per cluster)
merged = cluster_tracks(tracks, dist_eps=20.0, angle_eps=5.0)

# DataFrame → DataFrame (processes each view_id/slice_idx group)
import pandas as pd
df = pd.read_parquet("tracks.parquet")
df_merged = cluster_df(df, dist_eps=20.0, angle_eps=5.0)
```

### Parameters

| Parameter | Default | Description |
|---|---|---|
| `dist_eps` | `20.0` | ρ tolerance in pixels |
| `angle_eps` | `5.0` | θ tolerance in degrees |

## Web Viewer

Browse SPNG data in a browser and interactively control the processing
pipeline.

The three viewer pages share a single server process and can be accessed at:

| URL | Description |
|---|---|
| `http://localhost:8000/` | Redirect to Image Viewer |
| `http://localhost:8000/view/` | **Image Viewer** — live pipeline, SPNG browsing |
| `http://localhost:8000/results/` | **Results Viewer** — stored track images and stats |
| `http://localhost:8000/viewer3d/` | **3D Viewer** — interactive 3D track visualization |

Each page has navigation buttons to switch between the others.

### Starting the Server

```bash
# In the data directory (uses current directory as root)
cd /path/to/data && e07view

# Explicit directory
e07view /path/to/data/root

# Open browser automatically
e07view /path/to/data/root --open

# Custom host / port
e07view /path/to/data/root --host 0.0.0.0 --port 8080

# Open at a specific sub-path on launch
e07view /path/to/data/root --start MOD108/PL12

# Load analysis results to enable the Results Viewer
e07view /path/to/data/root --results tracks.db
```

`python -m e07fullscan.server` works as an alias if `e07view` is not on PATH.

To run on KEKCC and access from a local machine, use an SSH tunnel:

```bash
ssh -L 8000:localhost:8000 username@login.kekcc.jp
```

Then open `http://localhost:8000` in your browser.

### Controls

| Action | Effect |
|---|---|
| Click a JSON file in the sidebar | Load the Z stack |
| Mouse wheel / left-right arrow keys | Switch Z slice |
| VIEW: FIT/ACTUAL | Toggle fit ↔ actual-size view |
| Drag in actual-size view | Pan |
| ORIGINAL toggle | Show processed image alongside the original |
| STATS toggle | Show/hide pipeline statistics histograms below the image |
| RESET PARAMS button | Reset all pipeline parameters to defaults |

### Processing Pipeline

Each step can be toggled on/off individually via checkboxes in the sidebar.
Enabled steps are applied in order. All parameters are adjustable in
real time via sliders; defaults are defined in `config/default.yaml`.

| # | Step | Processing | Default Parameters |
|---|---|---|---|
| 1 | **Z-Projection** | Average neighbouring z-slices to boost track SNR | half=4 (9 slices total) |
| 2 | **Fog Removal** | Fog removal using Gaussian blur and subtraction | ksize=51 |
| 3 | **Threshold (Otsu)** | Auto-threshold binarization via Otsu's method | — |
| 4 | **Noise Removal** | Contour filtering by area and compactness | area_max=100, compactness=50 |
| 5 | **Hough Lines** | Track overlay with green lines via HoughLinesP | minLineLength=25, maxLineGap=4 |
| 6 | **Tracks Only** | Green track lines on black background (no binary dots) | — |

### Statistics Panel

The STATS panel shows four histograms that update with each slice and
parameter change:

- **Pixel intensity** — raw vs. after fog removal, with Otsu threshold marked
- **Blob area** — before/after noise removal (log scale)
- **Track length** — distribution with minLineLength threshold marked
- **Track angle** — 0–180°

![Pipeline: all 6 processing steps from raw scan to track detection](docs/pipeline.png)

## Results Viewer

When `--results` is given, a separate results page is available at
`http://localhost:8000/results/`. It displays pre-computed tracks from
the analysis database without re-running the pipeline.

| Control | Effect |
|---|---|
| View selector | Switch between JSON views in the results |
| Slice slider / arrow keys | Step through slices |
| STATS toggle | Show angle and length histograms for the slice |

## 3D Track Viewer

When `--results` is given, an interactive 3D viewer is available at
`http://localhost:8000/viewer3d/`. It renders stored track segments as
3D lines in (X, Y, Z) space using Plotly.js (loaded from CDN in the
browser).

| Control | Effect |
|---|---|
| View selector | Switch between JSON views |
| Cluster checkbox | Apply duplicate-segment clustering before display |
| Angle range | Filter tracks by angle (0–180°) |
| Min Length | Hide segments shorter than this value (px) |
| Slice Range | Restrict to a subset of Z-slices |
| RELOAD button | Fetch and redraw with current settings |

Track segments are coloured by angle using the Turbo colorscale.
Rotate and zoom with mouse drag / scroll.

## Tests

```bash
pytest        # run all tests
pytest -v     # verbose output
```

Tests cover the tracking library (`tracking/`), batch CLI (`analyze/`),
and results viewer (`server/results.py`).
