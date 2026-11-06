"""Shared paths and helpers for the course catalog pipeline."""
from __future__ import annotations

import csv
from datetime import date, datetime
import io
import os
from pathlib import Path
import time
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

PACKAGE = Path(__file__).resolve().parent
ROOT = PACKAGE.parent
INPUTS = PACKAGE / "inputs"
DATA = ROOT / "data"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"


def today_kst() -> date:
    return datetime.now(ZoneInfo("Asia/Seoul")).date()


def work_dir() -> Path:
    """Scratch folder for crawl results. Never committed (.tmp/ is ignored)."""
    path = Path(os.environ.get("CATALOG_WORK") or ROOT / ".tmp" / "catalog_work")
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_csv(path: Path | str) -> list[dict[str, str]]:
    with io.open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path | str, fieldnames: list[str], rows: Iterable[Mapping[str, Any]]) -> None:
    with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def session():
    import requests

    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def with_retry(call, attempts: int = 3, wait: float = 2.0):
    """Run call(); retry on any error, waiting longer each time. The last error is raised."""
    for attempt in range(attempts):
        try:
            return call()
        except Exception:
            if attempt == attempts - 1:
                raise
            time.sleep(wait * (attempt + 1))
