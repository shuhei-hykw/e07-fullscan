# Coding Rules

## Language
- Always respond in Japanese

## Package structure
- Main package: e07fullscan
- Subpackages: io, tracking, analyze, merge, clustering, server, utils

## Style
- Indentation: 2 spaces (never tabs)
- In-code comments: English only

## Error handling
- Include essential error guards, but keep code concise and minimal

## Formatting
- Line length: 79 characters max
- Avoid magic numbers; always assign named constants

## Documentation
- Always update ANALYSIS.md and README.md in English
- ANALYSIS.md is a **chronological development diary** (lab notebook style).
  Record not just results but also discussions, hypotheses, dead ends,
  and the reasoning behind decisions.
  Each entry is dated and appended at the bottom; never reorganise or remove
  existing entries. New entries go under `## YYYY-MM-DD — <title>`.
