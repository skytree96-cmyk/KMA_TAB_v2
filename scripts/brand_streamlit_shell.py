"""Brand the initial HTML shell in the disposable Render/CI installation.

Streamlit 1.61.1 sends this shell before Python page configuration is available.
The dependency is pinned in requirements.txt; unexpected shell markup fails the
build instead of silently shipping the default tab branding.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / "assets" / "kmatap-favicon.png"


def brand_static_shell(static_dir: Path) -> str:
    icon_bytes = ICON.read_bytes()
    if not icon_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("KMA TAP favicon must be a PNG")
    filename = "kmatap-favicon-" + hashlib.sha256(icon_bytes).hexdigest()[:12] + ".png"
    index_path = static_dir / "index.html"
    original = index_path.read_text(encoding="utf-8")
    branded, title_count = re.subn(r"<title>[^<]*</title>", "<title>KMA TAP</title>", original)
    # Use the standard rel=icon. In pinned Streamlit 1.61.1 the navigation
    # fallback only changes link[rel='shortcut icon']; it must not restore an
    # old, immutable-cached favicon.png while Python initializes the session.
    branded, icon_count = re.subn(
        r'<link\s+rel="(?:shortcut icon|icon)"[^>]*>',
        f'<link rel="icon" type="image/png" href="./{filename}" />',
        branded,
    )
    if title_count != 1 or icon_count != 1:
        raise RuntimeError("Unexpected Streamlit HTML shell; tab branding was not applied")
    (static_dir / filename).write_bytes(icon_bytes)
    (static_dir / "favicon.png").write_bytes(icon_bytes)
    index_path.write_text(branded, encoding="utf-8", newline="\n")
    return filename


def main() -> None:
    import streamlit
    filename = brand_static_shell(Path(streamlit.__file__).resolve().parent / "static")
    print(f"KMA TAP browser shell ready: {filename}", flush=True)


if __name__ == "__main__":
    main()
