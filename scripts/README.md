# scripts/

The everyday operation surface is the repo-root run.py. The files here are the
implementations it delegates to, plus a few entry points that must stay shell.

## Operation surface (use this)

    python run.py <command> [args]      # python run.py --help

run.py subcommands: track, view, merge-tracks, vertices, merge-vertices, crops,
review, map, click, submit-tracking, submit-vertices.

## Monitoring (separate, not in run.py)

    python scripts/monitor.py --pipeline           # overview + next step
    python scripts/monitor.py --pipeline --loop 30
    python scripts/monitor.py --job-name <name> --log-dir logs/kekcc   # live job
    python scripts/monitor.py --log analyze.log --output out.parquet   # local

scripts/status.py is a deprecated wrapper for monitor.py --pipeline.

## Diagnostics (in the package)

    python -m module.diagnostics.step5_compat
    python -m module.diagnostics.lowsp_diag
    python -m module.diagnostics.lowsp_spread_radius
    python -m module.diagnostics.bg_cost_spread

## Files here

- monitor.py - live job progress (--job-name/--log) + pipeline overview
  (--pipeline); single monitor entry point.
- status.py - deprecated wrapper to monitor.py --pipeline.
- active pipeline CLIs delegated to by run.py: find_vertices.py,
  merge_vertices.py, crop_vertices.py, review_crops.py, vertex_map.py,
  merge_chunks.py, click_vertex.py, submit_kekcc.py, submit_vertex_kekcc.py.
- KEKCC/LSF shell entry points (bsub execs them per task): kekcc_job.sh,
  kekcc_vertex.sh, analyze.sh (e07analyze wrapper teeing a log for monitor.py),
  run_pipeline_v6.sh (step-by-step v6 pipeline).
- legacy/ - historical pair scripts (superseded 2026-05-14); see legacy/README.md.
