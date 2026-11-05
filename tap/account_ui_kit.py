"""HTML building blocks shared by the account screens: sections, stat tiles, bars, chips, notes.

Every value is escaped here, so callers pass plain text. The styles are the v3 section rules
in assets/console-v2.css. Headings are plain divs on purpose: the sheet's h1~h3 rules and the
Markdown anchor styling must not leak into these blocks.
"""
from __future__ import annotations

from contextlib import contextmanager
from html import escape
from typing import Iterable, Iterator, Sequence

import streamlit as st


def icon(name: str) -> str:
    """A Material Symbols glyph; Streamlit bundles the font for its own icons."""
    return f'<span class="tap-ms" aria-hidden="true">{escape(name)}</span>'


def chip(text: str, *, icon_name: str = "", tone: str = "") -> str:
    """Small status pill. tone: '' (grey), 'ok' (teal), 'todo' (muted), 'warn' (orange)."""
    classes = "tap-chip" + (f" is-{tone}" if tone else "")
    return f'<span class="{classes}">{icon(icon_name) if icon_name else ""}{escape(text)}</span>'


def section_head(icon_name: str, title: str, caption: str = "", *, chips: Iterable[str] = ()) -> str:
    right = "".join(chips)
    return (f'<div class="tap-sec-head"><div><span class="tap-sec-ic" aria-hidden="true">{escape(icon_name)}</span>'
            f'<div><div class="tap-sec-title">{escape(title)}</div>'
            + (f'<div class="tap-sec-cap">{escape(caption)}</div>' if caption else "") + "</div></div>"
            + (f'<div class="tap-chips">{right}</div>' if right else "") + "</div>")


@contextmanager
def section(key: str, icon_name: str, title: str, caption: str = "", *, tone: str = "",
            chips: Iterable[str] = ()) -> Iterator[None]:
    """A titled panel. tone 'soft' (grey fill) or 'tint' (teal fade) tells sections of another kind apart."""
    if tone not in {"", "soft", "tint"}:
        raise ValueError("tone must be '', 'soft' or 'tint'")
    with st.container(key="tap_sec_" + (tone + "_" if tone else "") + key):
        st.html(section_head(icon_name, title, caption, chips=chips))
        yield


def stat_tiles(items: Sequence[tuple[str, str, str, float | None, bool]]) -> str:
    """Tiles of (label, value, unit, fill rate 0~100 or None, low)."""
    tiles = []
    for label, value, unit, rate, low in items:
        bar = "" if rate is None else f'<div class="tap-bar"><i style="width:{max(0.0, min(100.0, float(rate))):.0f}%"></i></div>'
        tiles.append(f'<div class="tap-stat{" is-low" if low else ""}"><span>{escape(label)}</span>'
                     f'<strong>{escape(value)}' + (f"<small>{escape(unit)}</small>" if unit else "") + f"</strong>{bar}</div>")
    return f'<div class="tap-stats">{"".join(tiles)}</div>'


def _width(value: float | None, maximum: float) -> str:
    if value is None or maximum <= 0:
        return "0"
    return f"{max(0.0, min(100.0, float(value) / maximum * 100)):.0f}"


def bar_rows(rows: Sequence[tuple[str, float | None, str]], *, maximum: float = 100) -> str:
    """One bar per (label, value, text)."""
    body = "".join(f'<div class="tap-brow"><span>{escape(label)}</span><div class="tap-track"><i style="width:{_width(value, maximum)}%"></i></div>'
                   f"<em>{escape(text)}</em></div>" for label, value, text in rows)
    return f'<div class="tap-bars">{body}</div>'


def pair_bar_rows(rows: Sequence[tuple[str, float | None, float | None, str]], *, maximum: float = 5,
                  labels: tuple[str, str] = ("교육 전", "교육 후")) -> str:
    """Pre and post readings of one scale, side by side, with a legend."""
    body = "".join(f'<div class="tap-brow"><span>{escape(label)}</span>'
                   f'<div class="tap-track"><i class="is-pre" style="width:{_width(pre, maximum)}%"></i></div>'
                   f'<div class="tap-track"><i style="width:{_width(post, maximum)}%"></i></div><em>{escape(text)}</em></div>'
                   for label, pre, post, text in rows)
    legend = f'<div class="tap-legend"><span><i class="is-pre"></i>{escape(labels[0])}</span><span><i></i>{escape(labels[1])}</span></div>'
    return f'<div class="tap-bars is-pair">{body}{legend}</div>'


HEAT_LOW, HEAT_HIGH = (242, 246, 255), (11, 79, 204)  # #F2F6FF → #0B4FCC, as in the PDF


def heatmap(columns: Sequence[str], rows: Sequence[tuple], *, hidden: str = "비공개") -> str:
    """A table of 1~5 means, shaded by value: rows are (label, note, [(mean, change), ...]); None hides a cell.

    A fourth item, when given, replaces the row's cells with that one line (a department hidden as a whole).
    """
    head = "".join(f"<th>{escape(name)}</th>" for name in columns)
    body = []
    for label, note, cells, *whole in rows:
        if whole and whole[0]:
            body.append(f'<tr><th>{escape(label)}<small>{escape(note)}</small></th>'
                        f'<td class="is-hidden is-whole" colspan="{len(columns)}">{escape(whole[0])}</td></tr>')
            continue
        tds = []
        for mean, change in cells:
            if mean is None:
                tds.append(f'<td class="is-hidden">{escape(hidden)}</td>')
                continue
            # Same scale as the PDF: 1 is the palest blue, 5 the deep blue; dark cells switch to white text.
            share = max(0.0, min(1.0, (mean - 1) / 4))
            red, green, blue = (round(low + (high - low) * share) for low, high in zip(HEAT_LOW, HEAT_HIGH))
            ink = "is-dark" if share > 0.7 else ""
            delta = f"<small>{escape(signed(change))}</small>" if change is not None else ""
            tds.append(f'<td class="{ink}" style="background:rgb({red} {green} {blue})">{mean:.2f}{delta}</td>')
        body.append(f"<tr><th>{escape(label)}<small>{escape(note)}</small></th>{''.join(tds)}</tr>")
    return f'<div class="tap-heat-wrap"><table class="tap-heat"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


def notes(items: Sequence[tuple[str, str]]) -> str:
    """Bulleted follow-up lines of (text, tone); tone '' or 'warn'."""
    body = "".join(f'<li class="is-{tone}">{icon("priority_high" if tone == "warn" else "info")}<span>{escape(text)}</span></li>'
                   if tone else f'<li>{icon("info")}<span>{escape(text)}</span></li>' for text, tone in items)
    return f'<ul class="tap-notes">{body}</ul>'


def foot(text: str) -> str:
    """Small print under a section's content."""
    return f'<div class="tap-foot">{escape(text)}</div>'


def fmt(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}"


def signed(value: float | None) -> str:
    if value is None:
        return "—"
    return "0.00" if round(float(value), 2) == 0 else f"{float(value):+.2f}"
