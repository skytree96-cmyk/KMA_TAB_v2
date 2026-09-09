"""KMA administration of the wording used for new assessment projects."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import streamlit as st


LOGGER = logging.getLogger(__name__)
PREFIX = "question_bank_"


def _updated_time(value: Any) -> str:
    if value is None:
        return "미수정"
    try:
        return datetime.fromtimestamp(float(value), ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OverflowError, OSError):
        return "확인 불가"


def _clear_editor(*, clear_selection: bool = False) -> None:
    for suffix in ("draft", "text"):
        st.session_state.pop(PREFIX + suffix, None)
    if clear_selection:
        st.session_state[PREFIX + "select"] = None


def _start_editor(row: Mapping[str, Any]) -> dict[str, Any]:
    draft = {"question_code": str(row["question_code"]), "base_revision": int(row.get("revision") or 0), "conflict": False}
    st.session_state[PREFIX + "draft"] = draft
    st.session_state[PREFIX + "text"] = str(row.get("revised_text") or "")
    return draft


def _failure(exc: Exception) -> str:
    messages = {
        "AuthenticationError": "로그인 시간이 만료되었습니다. 다시 로그인해 주세요.",
        "AuthorizationError": "KMA 관리자만 운영 문항을 수정할 수 있습니다.",
        "ValidationError": "운영 문구를 1~2000자로 입력해 주세요.",
        "RateLimitError": "잠시 후 다시 시도해 주세요. 요청이 일시적으로 많습니다.",
    }
    return messages.get(type(exc).__name__, "처리하지 못했습니다. 잠시 후 다시 시도해 주세요.")


def render_question_bank(store: Any, token: str, principal: Mapping[str, Any]) -> None:
    if principal.get("role") != "kma":
        st.error("KMA 관리자만 운영 문항을 수정할 수 있습니다.")
        return
    owner = str(principal.get("id") or principal.get("user_id") or "")
    if st.session_state.get(PREFIX + "owner") != owner:
        for key in list(st.session_state):
            if key.startswith(PREFIX):
                st.session_state.pop(key, None)
        st.session_state[PREFIX + "owner"] = owner
    if st.session_state.pop(PREFIX + "reload_after_save", False):
        _clear_editor()
    st.title("문항 관리")
    st.caption("운영 문구 수정은 새 프로젝트부터 적용되며, 기존 프로젝트는 수정 전 문구를 유지합니다.")
    if notice := st.session_state.pop(PREFIX + "notice", None):
        st.success(notice)
    st.button("목록 새로고침", key=PREFIX + "refresh", on_click=_clear_editor, kwargs={"clear_selection": True})
    try:
        rows = [row for row in store.list_question_bank(token) if row.get("active", True)]
    except Exception as exc:
        LOGGER.error("Question bank listing failed: %s", type(exc).__name__)
        st.error(_failure(exc))
        return
    if not rows:
        _clear_editor(clear_selection=True)
        st.info("등록된 운영 문항이 없습니다.")
        return
    modules = sorted({str(row.get("module_group") or "미분류") for row in rows})
    module_key = PREFIX + "module"
    if st.session_state.get(module_key) not in modules:
        st.session_state[module_key] = None
    left, right = st.columns(2)
    with left:
        module = st.selectbox("모듈", [None, *modules], format_func=lambda value: value or "전체 모듈", key=module_key)
    module_rows = [row for row in rows if module is None or str(row.get("module_group") or "미분류") == module]
    factors = {str(row["factor_code"]): str(row.get("factor_name_ko") or row["factor_code"]) for row in module_rows}
    factor_key = PREFIX + "factor"
    if st.session_state.get(factor_key) not in factors:
        st.session_state[factor_key] = None
    with right:
        factor = st.selectbox("역량", [None, *factors], format_func=lambda value: f"{factors[value]} · {value}" if value is not None else "전체 역량", key=factor_key)
    matched = [row for row in module_rows if factor is None or str(row["factor_code"]) == factor]
    by_code = {str(row["question_code"]): row for row in matched}
    selection_key = PREFIX + "select"
    if st.session_state.get(selection_key) not in by_code:
        _clear_editor(clear_selection=True)
    st.caption(f"운영 문항 {len(matched)}개 · 최종 수정 시각은 한국시간 기준입니다.")
    st.dataframe([
        {"문항 코드": row["question_code"], "모듈": row.get("module_group", ""),
         "역량": row.get("factor_name_ko", ""), "운영 문구": row.get("revised_text", ""),
         "최종 수정 시각": _updated_time(row.get("updated_at")), "수정자": row.get("updated_by") or "—"}
        for row in matched
    ], hide_index=True, width="stretch", row_height=80,
        column_config={"운영 문구": st.column_config.TextColumn("운영 문구", width="large")})
    selected = st.selectbox(
        "편집할 문항", list(by_code), key=selection_key, index=None, placeholder="문항을 선택하세요",
        format_func=lambda value: f"{value} · {by_code[value].get('factor_name_ko', '')}",
    )
    if selected is None:
        _clear_editor()
        return
    row = by_code[selected]
    draft = st.session_state.get(PREFIX + "draft")
    if not draft or draft.get("question_code") != selected:
        draft = _start_editor(row)
    if st.button("최신 문구 불러오기", key=PREFIX + "load_latest", help="작성 중인 문구를 현재 저장된 최신 문구로 바꿉니다."):
        draft = _start_editor(row)
    if int(row.get("revision") or 0) != draft["base_revision"]:
        draft["conflict"] = True
    if draft["conflict"]:
        st.warning("이 문항이 다른 관리자에 의해 수정되었습니다. 작성 중인 문구는 보존되어 있습니다. 최신 문구를 불러온 뒤 다시 편집해 주세요.")
    st.caption(f"{selected} · 최종 수정 {_updated_time(row.get('updated_at'))} · 수정자 {row.get('updated_by') or '—'}")
    with st.form(PREFIX + "edit_form"):
        text = st.text_area("운영 문구", key=PREFIX + "text", max_chars=2000, height=160, help="1~2000자로 입력해 주세요.")
        submitted = st.form_submit_button("운영 문구 저장", type="primary")
    if not submitted:
        return
    text = text.strip()
    if not 1 <= len(text) <= 2000:
        st.error("운영 문구를 1~2000자로 입력해 주세요.")
        return
    try:
        store.save_question_text(token, selected, text, expected_revision=draft["base_revision"])
    except Exception as exc:
        LOGGER.error("Question bank save failed: %s", type(exc).__name__)
        if type(exc).__name__ == "ConflictError":
            draft["conflict"] = True
            st.error("다른 관리자가 먼저 수정하여 저장하지 못했습니다. 작성 중인 문구는 보존되어 있습니다. 최신 문구를 불러온 뒤 다시 편집해 주세요.")
        else:
            st.error(_failure(exc))
        return
    st.session_state[PREFIX + "reload_after_save"] = True
    st.session_state[PREFIX + "notice"] = "운영 문구를 저장했습니다. 새 프로젝트부터 적용됩니다."
    st.rerun()
