from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WrittenReport:
    json_path: Path
    markdown_path: Path


def default_generated_reports_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "reports" / "generated"
