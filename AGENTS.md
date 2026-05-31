# Coding Rules

## Language
- Always respond in Japanese

## Package structure
- Main package: module (renamed from e07fullscan on 2026-05-30)
- Subpackages: io, tracking, analyze, merge, clustering, server, utils,
  diagnostics, review
- Shared module: preprocess (branch-neutral fog/Otsu/noise preprocessing)
- Monitor/status helpers: module/pipeline_status.py (pipeline overview);
  module/utils/job_monitor.py (live-job monitor body)

## Style
- Indentation: 2 spaces (never tabs)
- In-code comments: English only

## Error handling
- Include essential error guards, but keep code concise and minimal

## Formatting
- Line length: 79 characters max
- Avoid magic numbers; always assign named constants

## Documentation
- Always update and review ANALYSIS.md and README.md in English
- Always update ANALYSIS_ja.md in Japanese (mirrors ANALYSIS.md)
- ANALYSIS.md / ANALYSIS_ja.md are **chronological development diaries**
  (lab notebook style). Record not just results but also discussions,
  hypotheses, dead ends, and the reasoning behind decisions.
  Each entry is dated and appended at the bottom; never reorganise or remove
  existing entries. New entries go under `## YYYY-MM-DD — <title>`.

## Simplification Principle
- Prefer Occam's razor: reduce visible concepts, entry points, and files
  rather than adding categories or wrappers.
- The normal user-facing operation surface should be small and obvious.
  Prefer a thin repo-root `run.py` for everyday pipeline actions and one
  clear monitor concept.
- Do not add new subdirectories under `scripts/`. If scripts are confusing,
  move reusable logic into `module/` and reduce the number of visible scripts.
- Diagnostics and legacy code should not appear as everyday commands.

## Agent Coordination
- At the start of every session, especially stateless `codex exec`, cron, or
  tmux watcher runs, reconstruct working memory by reading:
  `AGENTS.md`, `CLAUDE.md`, `discussion.md`, `discussion_ja.md`,
  `ANALYSIS.md`, and `ANALYSIS_ja.md`.
- Always check both `discussion.md` and `discussion_ja.md` before starting
  repository work, before editing shared files, and before final reporting.
- Treat new entries in those files as active coordination state from the
  other agent or the user.
- New Markdown log entries should include both date and time, preferably in
  `YYYY-MM-DD HH:MM JST` form. Do not rewrite older date-only entries just to
  add times.
- In this collaboration, Codex is discussion-main: Codex monitors and
  maintains `discussion.md` / `discussion_ja.md`, while Claude performs
  actual coding and implementation work.
- Codex must treat non-Markdown files as read-only. Codex may inspect code,
  scripts, configs, data files, and generated outputs for context, but must
  not edit them.
- Codex Markdown edits should stay limited to discussion coordination and
  user-requested documentation updates.
- For long-running monitoring, persistent state must live in repository
  Markdown files, not in transient model memory. If a watcher is restarted,
  it must infer state from the files listed above.
- Keep both discussion files append-only. Never reorganise or remove existing
  entries.
- Before editing files that another agent lists as active, record the intent
  in both discussion files and avoid the edit unless the user explicitly asks
  for it or the coordination note makes the ownership clear.
- When launching jobs, generating outputs, or changing scripts, record the
  intended input files, output files/directories, and owned files in the
  discussion logs first.
- If a conclusion or result matters beyond short-term coordination, also
  append it to `ANALYSIS.md` and `ANALYSIS_ja.md` as dated diary entries.
