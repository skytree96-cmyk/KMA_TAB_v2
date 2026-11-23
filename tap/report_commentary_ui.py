"""The "한눈에 보는 해설" block at the top of the organization report.

Shown only when a commentary exists or can be made. When the API is off, out of credit or over
budget and nothing was stored, the block is not drawn and the report reads as it does today.
"""
from __future__ import annotations

from html import escape
import re
from typing import Any, Mapping

import streamlit as st

from tap.account_ui_kit import icon
from tap.report_commentary import commentary_state, make_commentary

FINDING_ICONS = ("trending_up", "account_tree", "work_history", "insights")
# Split after a full stop followed by a space; "3.12" has no space and "보다 " has no stop.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
NOTICE = "※ 집계 수치로 자동 작성한 해설입니다. 숫자는 아래 차트가 기준입니다."


def _lines(text: str) -> str:
    """One sentence per line, as the report PDFs do."""
    return "".join(f"<p>{escape(part)}</p>" for part in _SENTENCE_END.split(str(text).strip()) if part)


def commentary_html(stored: Mapping[str, Any], *, older: bool = False) -> str:
    result = stored["result"]
    finds = "".join(
        f'<div class="tap-cm__find"><div class="tap-cm__find-top"><span class="tap-cm__find-ic">'
        f'{icon(FINDING_ICONS[index % len(FINDING_ICONS)])}</span><b>{escape(str(item["title"]))}</b></div>'
        f'{_lines(item["body"])}</div>'
        for index, item in enumerate(result["findings"]))
    acts = "".join(f"<li><b>{index}</b><span>{escape(str(text))}</span></li>"
                   for index, text in enumerate(result["actions"], start=1))
    stale = ('<div class="tap-cm__stale">응답이 더 들어와 숫자가 바뀌었습니다. 아래 해설은 '
             f'{escape(str(stored.get("created_at", "")))} 기준입니다.</div>') if older else ""
    return (f'<div class="tap-cm"><div class="tap-cm__top"><div class="tap-cm__label">{icon("auto_awesome")}한눈에 보는 해설</div>'
            f'<div class="tap-cm__head">{escape(str(result["headline"]))}</div></div>{stale}'
            f'<div class="tap-cm__body"><div class="tap-cm__finds">{finds}</div>'
            f'<div class="tap-cm__acts"><div class="tap-cm__acts-title">{icon("checklist")}다음에 할 일</div><ol>{acts}</ol></div></div>'
            f'<div class="tap-cm__foot"><span>{escape(NOTICE)}</span>'
            f'<span>{escape(str(stored.get("created_at", "")))} 작성</span></div></div>')


MAKE_HTML = ('<div class="tap-cm-make"><b>한눈에 보는 해설</b><span>역량 변화, 부서 차이, 현업 적용 여건을 묶어 읽은 해설을 만듭니다. '
             "20~40초 걸리고, 한 번 만들면 이 리포트를 여는 사람 모두에게 그대로 보입니다.</span></div>")


def render_commentary(store: Any, project: Mapping[str, Any], payload: Mapping[str, Any] | None) -> None:
    if not payload:
        return
    project_id = str(project["id"])
    state = commentary_state(store, project_id, payload)
    flash_key = f"tap_cm_failed_{project_id}"
    shown = state["current"] or state["older"]
    if shown:
        st.html(commentary_html(shown, older=state["current"] is None))
    elif state["can_make"]:
        st.html(MAKE_HTML)
    if state["can_make"]:
        label = ("해설 만들기" if not shown else "새 숫자로 다시 만들기" if state["current"] is None else "다시 만들기")
        if st.button(f"{label} (이번 달 {state['remaining']}회 남음)", key=f"tap_cm_make_{project_id}",
                     icon=":material/auto_awesome:", type="secondary"):
            with st.spinner("해설을 쓰는 중입니다"):
                made = make_commentary(store, project_id, payload)
            if made is None:
                st.session_state[flash_key] = True
            st.rerun()
    if st.session_state.pop(flash_key, False):
        st.caption("지금은 해설을 만들 수 없습니다. 아래 리포트는 그대로 보실 수 있습니다.")
