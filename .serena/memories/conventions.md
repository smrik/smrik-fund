# Conventions

- Use type hints and `from __future__ import annotations` in new Python modules.
- Normalize ticker input with `.strip().upper()` before EDGAR calls and output paths.
- Use `pathlib.Path` for filesystem paths and create output directories with `mkdir(parents=True, exist_ok=True)`.
- Keep EDGAR retrieval, DataFrame transformation, and file output in small functions.
- Preserve source labels and concepts from EdgarTools; do not drop `concept` or `standard_concept` columns.