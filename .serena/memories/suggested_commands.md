# Suggested Commands

- Install/update the environment: `uv sync`.
- Run the CLI: `.venv\\Scripts\\smrik-fund.exe --help`.
- Parse one ticker: `.venv\\Scripts\\smrik-fund.exe parse MSFT`.
- Run tests: `.venv\\Scripts\\python.exe -m unittest discover -s tests -v`.
- Lint: `.venv\\Scripts\\ruff.exe check src tests`.
- Format check: `.venv\\Scripts\\ruff.exe format --check src tests`.
- Compile check: `.venv\\Scripts\\python.exe -m compileall -q src tests`.
- If uv cache permissions fail on Windows, pass a project-local cache path such as `uv --cache-dir .uv-cache sync`.