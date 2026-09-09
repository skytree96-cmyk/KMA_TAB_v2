"""Shared presentation for production account screens; no routing or data access."""
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def account_theme_css() -> str:
    css = (Path(__file__).resolve().parents[1] / "assets" / "account-ui.css").read_text(encoding="utf-8")
    return "<style>" + css + "</style>"


@lru_cache(maxsize=1)
def workspace_theme_css() -> str:
    css = (Path(__file__).resolve().parents[1] / "assets" / "workspace-ui.css").read_text(encoding="utf-8")
    return "<style>" + css + "</style>"
