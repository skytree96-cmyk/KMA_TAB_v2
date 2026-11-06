"""Course cards shared by the participant report and the organization report screens.

Picks are grouped by competency. Each group opens with the number, the score reason and a
gap bar (score against the project target), then shows its courses as small cards: thumbnail,
source, title, schedule and a link button. Everything is one HTML block, so a competency with
three courses takes one row instead of a screen.
"""
from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

import streamlit as st

from tap.account_ui_kit import icon

SOURCE_LABELS = {
    "public_edu_center": "공개교육",
    "studio_elearning": "이러닝",
    "b2b_inquiry": "단체교육 문의",
    "studio_original": "stud.io",
}
BUTTON_LABELS = {
    "public_edu_center": "최신 일정 보기",
    "studio_elearning": "수강 페이지 보기",
    "b2b_inquiry": "과정 안내 보기",
}
BUTTON_ICONS = {
    "public_edu_center": "calendar_month",
    "studio_elearning": "play_circle",
    "b2b_inquiry": "open_in_new",
}
# Only http(s) destinations become links; anything else in the catalog is shown without a button.
_SAFE_SCHEMES = ("https://", "http://")


def _scale_percent(value: Any) -> float | None:
    """Position of a 1~5 score on the bar, 0~100."""
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(100.0, (score - 1) / 4 * 100))


def gap_bar_html(score: Any, target: Any) -> str:
    """Bar of the score on the 1~5 scale with a tick at the project target."""
    fill, tick = _scale_percent(score), _scale_percent(target)
    if fill is None or tick is None:
        return ""
    return (f'<div class="tap-gap"><div class="tap-gap__track"><i style="width:{fill:.0f}%"></i><b style="left:{tick:.0f}%"></b></div>'
            f'<span><span>1</span><span>목표 {float(target):.1f}</span><span>5</span></span></div>')


def course_card_html(course: Mapping[str, Any]) -> str:
    source = str(course.get("source", ""))
    label = SOURCE_LABELS.get(source) or str(course.get("delivery_label") or "")
    thumb = str(course.get("thumb_url") or "")
    picture = f'<img src="{escape(thumb, quote=True)}" alt="" loading="lazy">' if thumb.startswith(_SAFE_SCHEMES) else ""
    body = (f'<div class="tap-course__thumb">{picture}<span class="tap-course__src">{escape(label)}</span></div>'
            f'<div class="tap-course__body"><div class="tap-course__title">{escape(str(course.get("title", "")))}</div>'
            + (f'<div class="tap-course__meta">{escape(str(course["schedule"]))}</div>' if course.get("schedule") else ""))
    url = str(course.get("url") or "")
    if url.startswith(_SAFE_SCHEMES):
        button = (f'<span class="tap-course__btn">{icon(BUTTON_ICONS.get(source, "open_in_new"))}'
                  f'{escape(BUTTON_LABELS.get(source, "KMA에서 과정 찾기"))}</span>')
        return (f'<a class="tap-course" href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
                f'{body}{button}</div></a>')
    return f'<div class="tap-course">{body}</div></div>'


def competency_group_html(number: int, rows: Sequence[Mapping[str, Any]]) -> str:
    first = rows[0]
    change = first.get("change")
    if isinstance(change, (int, float)) and change >= 0.2:
        advice_icon = "trending_up"
    elif isinstance(change, (int, float)) and change <= -0.2:
        advice_icon = "trending_down"
    else:
        advice_icon = "tips_and_updates"
    advice = (f'<div class="tap-advice">{icon(advice_icon)}<span>{escape(str(first["advice"]))}</span></div>'
              if first.get("advice") else "")
    return (f'<div class="tap-need"><div class="tap-need__head"><span class="tap-need__no">{number:02d}</span>'
            f'<div><b>{escape(str(first["factor_name_ko"]))}</b><small>{escape(str(first.get("reason", "")))}</small></div>'
            f'{gap_bar_html(first.get("score"), first.get("target"))}</div>'
            f'<div class="tap-need__body">{advice}<div class="tap-courses">{"".join(course_card_html(row) for row in rows)}</div></div></div>')


def holds_html(items: Sequence[Mapping[str, Any]], title: str, caption: str) -> str:
    from tap.account_insights import hold_note
    rows = "".join(f'<li><b>{escape(str(item["factor_name_ko"]))}</b><span>{escape(hold_note(item))}</span></li>' for item in items)
    return (f'<div class="tap-hold">{icon("construction")}<div><div class="tap-hold__title">{escape(title)}</div>'
            f'<div class="tap-hold__cap">{escape(caption)}</div><ul>{rows}</ul></div></div>')


def render_holds(items: Sequence[Mapping[str, Any]], title: str, caption: str) -> None:
    st.html(holds_html(items, title, caption))


def render_course_cards(courses: Sequence[Mapping[str, Any]], *, key_prefix: str = "") -> None:
    """Group picks by competency and draw each group as a numbered block of small cards."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for course in courses:
        groups.setdefault(str(course["factor_code"]), []).append(course)
    if not groups:
        return
    st.html('<div class="tap-needs">' + "".join(competency_group_html(number, rows) for number, rows in enumerate(groups.values(), 1)) + "</div>")
