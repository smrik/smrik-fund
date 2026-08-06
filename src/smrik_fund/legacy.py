import subprocess
from pathlib import Path

DEFAULT_LEGACY_REPO = Path(r"C:\Projects\03-Finance\ai-fund")


def run_legacy_pipeline(
    ticker: str,
    legacy_repo: Path = DEFAULT_LEGACY_REPO,
) -> None:
    """Run the existing ai-fund ingestion pipeline."""

    if not legacy_repo.exists():
        raise FileNotFoundError(f"Legacy repository does not exist: {legacy_repo}")

    command = [
        "uv",
        "run",
        "--project",
        str(legacy_repo),
        "python",
        "-m",
        "src.stage_00_data.ingestion.cli",
        "run",
        "--ticker",
        ticker.upper(),
    ]

    subprocess.run(
        command,
        cwd=legacy_repo,
        check=True,
    )
