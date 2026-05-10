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
- ANALYSIS.md is a **chronological development diary**: each entry is dated,
  records what was done and found, and is appended at the bottom.
  Never reorganise or remove existing entries.
  New entries always go at the end under a `## YYYY-MM-DD — <title>` heading.
