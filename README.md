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

Dependencies: numpy, scipy, opencv-python, matplotlib, PyYAML  
Additional dependency for web viewer: flask

## Package Structure

```
e07fullscan/
├── io/
│   └── image_reader.py   # SPNG format reader
├── server/               # Web viewer (requires flask)
│   ├── app.py
│   └── __main__.py
├── tracking/             # Track finding (under development)
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

## Web Viewer

Browse SPNG data in a browser and interactively control the processing
pipeline.

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

![Pipeline: raw scan vs full pipeline with Hough line detection](docs/pipeline.png)

## Tests

```bash
pytest
```
