"""KMA TAP typographic identity, using bundled OFL-licensed Paperlogy fonts."""
from __future__ import annotations

import base64
from functools import lru_cache
from html import escape
from pathlib import Path


FONT_DIR = Path(__file__).resolve().parents[1] / "assets" / "fonts"
BRAND_VARIANTS = ("navy-teal", "navy", "teal", "reverse")
BRAND_DESCRIPTION = "교육 전·후\n변화 평가 플랫폼"


@lru_cache(maxsize=1)
def brand_css() -> str:
    """Return a style element; font loading makes no third-party requests."""
    faces = []
    for weight, filename in ((500, "Paperlogy-5Medium.woff2"), (800, "Paperlogy-8ExtraBold.woff2")):
        font = (FONT_DIR / filename).read_bytes()
        if font[:4] != b"wOF2":
            raise ValueError("Bundled Paperlogy font is invalid")
        encoded = base64.b64encode(font).decode("ascii")
        faces.append(
            "@font-face{font-family:'TAP Paperlogy';font-style:normal;"
            f"font-weight:{weight};font-display:swap;src:url(data:font/woff2;base64,{encoded}) format('woff2');}}"
        )
    return "<style>" + "".join(faces) + """
    .tap-ci {
      --ci-kma:#192c48; --ci-tap:#087f83; --ci-dot:#20c7dc; --ci-caption:#51657f;
      display:flex; align-items:center; gap:26px; flex-wrap:wrap;
      width:fit-content; max-width:100%; margin:0 0 22px; padding:0;
      text-align:left; color:var(--ci-kma);
    }
    .tap-ci .tap-ci-wordmark {
      display:inline-flex; align-items:baseline; gap:0; flex-shrink:0;
      font-family:'TAP Paperlogy',sans-serif !important; font-weight:800 !important;
      font-size:clamp(40px,5.8vw,76px); line-height:1.08; letter-spacing:-.055em;
      white-space:nowrap; font-synthesis:none; -webkit-font-smoothing:antialiased;
    }
    .tap-ci .tap-ci-kma,.tap-ci .tap-ci-tap {
      font-family:inherit !important; font-size:inherit !important;
      font-weight:inherit !important; line-height:inherit !important;
      letter-spacing:inherit !important;
    }
    .tap-ci .tap-ci-kma {color:var(--ci-kma);}
    .tap-ci .tap-ci-tap {color:var(--ci-tap);margin-left:.20em;}
    .tap-ci .tap-ci-dot {
      display:inline-block; width:.15em; height:.15em; margin-left:.08em;
      border-radius:50%; background:var(--ci-dot); flex-shrink:0;
    }
    .tap-ci .tap-ci-description {
      font-family:'TAP Paperlogy',sans-serif !important; font-weight:500 !important;
      font-size:14px !important; line-height:1.65 !important; letter-spacing:-.025em;
      color:var(--ci-caption); white-space:pre-line; margin:0; padding:1px 0 0;
    }
    .tap-ci--navy {--ci-tap:#192c48;}
    .tap-ci--teal {--ci-kma:#087f83;--ci-tap:#087f83;}
    .tap-ci--reverse {--ci-kma:#ffffff;--ci-tap:#ffffff;--ci-caption:#d8e4ef;}
    .tap-ci--compact {flex-direction:column;align-items:flex-start;gap:9px;margin:0 0 20px;}
    .tap-ci--compact .tap-ci-wordmark {font-size:32px;}
    .tap-ci--compact .tap-ci-description {font-size:10px !important;line-height:1.65 !important;}
    @media(max-width:640px) {
      .tap-ci {gap:12px;}
      .tap-ci:not(.tap-ci--compact) .tap-ci-description {font-size:12px !important;}
      .tap-ci--compact {gap:9px;}
    }
    </style>"""


def brand_html(compact: bool = False, variant: str = "navy-teal") -> str:
    """Return a static, accessible wordmark with validated color variants."""
    if variant not in BRAND_VARIANTS:
        raise ValueError("Unknown KMA TAP brand variant")
    classes = "tap-ci tap-ci--" + variant + (" tap-ci--compact" if compact else "")
    label = "KMA TAP · " + BRAND_DESCRIPTION.replace("\n", " ")
    return (
        f'<div class="{escape(classes, quote=True)}" role="img" aria-label="{escape(label, quote=True)}">'
        '<span class="tap-ci-wordmark" aria-hidden="true">'
        '<span class="tap-ci-kma">KMA</span><span class="tap-ci-tap">TAP</span>'
        '<span class="tap-ci-dot"></span></span>'
        f'<span class="tap-ci-description" aria-hidden="true">{escape(BRAND_DESCRIPTION)}</span></div>'
    )
