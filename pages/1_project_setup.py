from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta

import streamlit as st

from tap.data import load_competencies, questions_for_factors
from tap.selection import (
    MAX_JOB_FUNCTION,
    MAX_OPTIONAL,
    MAX_SPECIALTY,
    applicable_to_level,
    sanitize_selection,
    selection_errors,
)
from tap.state import ensure_state, reset_assessment
from tap.ui import callout, domain_header, page_header, setup_page, summary_strip


setup_page("프로젝트 설정", "T")
ensure_state(st.session_state)
competencies = load_competencies()
row_by_code = {row["factor_code"]: row for row in competencies}

level_labels = {"staff": "실무자", "manager": "관리자·리더", "executive": "임원"}


def _iso_date(value: object, fallback: date) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return fallback


def _initialize_checkbox(key: str, checked: bool) -> None:
    if key not in st.session_state:
        st.session_state[key] = checked


def _render_competency_cards(
    rows: list[dict],
    *,
    key_prefix: str,
    disabled_codes: set[str] | None = None,
    tag: str | None = None,
) -> list[str]:
    disabled_codes = disabled_codes or set()
    selected: list[str] = []
    columns = st.columns(2)
    for index, row in enumerate(rows):
        code = row["factor_code"]
        key = f"{key_prefix}_{code}"
        with columns[index % 2]:
            with st.container(border=True):
                checked = st.checkbox(
                    f"{row['factor_name_ko']}" + (f" · {tag}" if tag else ""),
                    key=key,
                    disabled=code in disabled_codes,
                )
                st.caption(row["definition"])
                indicators = [part.strip() for part in row["behavioral_indicators"].split("|") if part.strip()]
                if indicators:
                    st.caption("행동지표 · " + " / ".join(indicators[:2]))
        if checked:
            selected.append(code)
    return selected


def _render_limited_factor_checkboxes(
    rows: list[dict],
    *,
    key_prefix: str,
    previous: list[str],
    limit: int,
) -> list[str]:
    allowed_codes = {row["factor_code"] for row in rows}
    for row in competencies:
        key = f"{key_prefix}_{row['factor_code']}"
        _initialize_checkbox(key, row["factor_code"] in previous and row["factor_code"] in allowed_codes)
        if row["factor_code"] not in allowed_codes:
            st.session_state[key] = False

    selected_before = [
        row["factor_code"] for row in rows if st.session_state.get(f"{key_prefix}_{row['factor_code']}", False)
    ][:limit]
    for row in rows:
        code = row["factor_code"]
        st.session_state[f"{key_prefix}_{code}"] = code in selected_before

    columns = st.columns(2)
    selected: list[str] = []
    for index, row in enumerate(rows):
        code = row["factor_code"]
        key = f"{key_prefix}_{code}"
        is_selected = bool(st.session_state.get(key, False))
        disable = len(selected_before) >= limit and not is_selected
        with columns[index % 2]:
            with st.container(border=True):
                checked = st.checkbox(
                    row["factor_name_ko"],
                    key=key,
                    disabled=disable,
                )
                st.caption(row["definition"])
        if checked:
            selected.append(code)
    return selected


page_header(
    "프로젝트 만들기",
    "새 진단 프로젝트",
    "대상자에게 적용되는 기본역량을 확인하고 전문·미래역량 최대 3개와 직무역량 1개를 추가합니다.",
    badge="체크박스형 모듈 구성",
)

with st.container(border=True):
    st.markdown('<h3 class="tap-card-title">1. 프로젝트 기본정보</h3>', unsafe_allow_html=True)
    st.markdown(
        '<p class="tap-card-sub">교육 목적, 응답 대상과 기간을 먼저 설정합니다.</p>',
        unsafe_allow_html=True,
    )
    _initialize_checkbox("project_name_input_initialized", True)
    if "project_name_input" not in st.session_state:
        st.session_state.project_name_input = st.session_state.project_name
    project_name = st.text_input("프로젝트명", key="project_name_input")

    level_codes = list(level_labels)
    target_level = st.radio(
        "응답 대상",
        options=level_codes,
        format_func=level_labels.get,
        index=level_codes.index(st.session_state.target_level),
        horizontal=True,
        key="target_level_picker",
    )

    default_start = _iso_date(st.session_state.project_start_date, date.today() + timedelta(days=7))
    default_end = _iso_date(st.session_state.project_end_date, default_start + timedelta(days=11))
    date_left, date_right = st.columns(2)
    with date_left:
        start_date = st.date_input("응답 시작일", value=default_start, key="project_start_picker")
    with date_right:
        end_date = st.date_input("응답 마감일", value=default_end, key="project_end_picker")

base_rows = [
    row for row in competencies if row["active_for_scoring"] and row["library_type"] == "base"
]
applicable_base = [row for row in base_rows if applicable_to_level(row, target_level)]
base_codes = [row["factor_code"] for row in applicable_base]

with st.container(border=True):
    st.markdown('<h3 class="tap-card-title">2. 기본역량</h3>', unsafe_allow_html=True)
    st.markdown(
        '<p class="tap-card-sub">대상 수준에 적용되는 기본역량은 체크된 상태로 고정됩니다.</p>',
        unsafe_allow_html=True,
    )
    base_columns = st.columns(2)
    for index, row in enumerate(base_rows):
        applicable = row["factor_code"] in base_codes
        with base_columns[index % 2]:
            with st.container(border=True):
                st.checkbox(
                    f"{row['factor_name_ko']} · 기본",
                    value=applicable,
                    disabled=True,
                    key=f"base_{target_level}_{row['factor_code']}",
                )
                st.caption(row["definition"])
                if not applicable:
                    st.caption(f"현재 대상({level_labels[target_level]})에는 적용하지 않습니다.")

optional_rows = [
    row
    for row in competencies
    if row["active_for_scoring"]
    and row["library_type"] in {"specialty", "job_function"}
    and applicable_to_level(row, target_level)
]
previous_optional = [
    code
    for code in st.session_state.selected_factors
    if code in row_by_code and row_by_code[code]["library_type"] in {"specialty", "job_function"}
]
previous_optional = sanitize_selection(previous_optional, competencies, target_level)

for row in competencies:
    if row["library_type"] not in {"specialty", "job_function"}:
        continue
    key = f"optional_{row['factor_code']}"
    _initialize_checkbox(key, row["factor_code"] in previous_optional)
    if row not in optional_rows:
        st.session_state[key] = False

selected_pre = sanitize_selection(
    [
        row["factor_code"]
        for row in optional_rows
        if st.session_state.get(f"optional_{row['factor_code']}", False)
    ],
    competencies,
    target_level,
)
for row in optional_rows:
    st.session_state[f"optional_{row['factor_code']}"] = row["factor_code"] in selected_pre

counts = Counter(row_by_code[code]["library_type"] for code in selected_pre)
disabled_optional: set[str] = set()
for row in optional_rows:
    code = row["factor_code"]
    if code in selected_pre:
        continue
    library_type = row["library_type"]
    total_selected = counts["specialty"] + counts["job_function"]
    if total_selected >= MAX_OPTIONAL:
        disabled_optional.add(code)
    elif library_type == "specialty" and counts["specialty"] >= MAX_SPECIALTY:
        disabled_optional.add(code)
    elif library_type == "job_function" and counts["job_function"] >= MAX_JOB_FUNCTION:
        disabled_optional.add(code)

with st.container(border=True):
    st.markdown('<h3 class="tap-card-title">3. 선택역량</h3>', unsafe_allow_html=True)
    st.markdown(
        '<p class="tap-card-sub">목적에 필요한 역량만 선택합니다. 최대치에 도달하면 나머지 체크박스가 자동으로 잠깁니다.</p>',
        unsafe_allow_html=True,
    )
    specialty_rows = [row for row in optional_rows if row["library_type"] == "specialty"]
    job_rows = [row for row in optional_rows if row["library_type"] == "job_function"]

    domain_header("전문·미래역량", f"최대 {MAX_SPECIALTY}개")
    specialty_selected = _render_competency_cards(
        specialty_rows,
        key_prefix="optional",
        disabled_codes=disabled_optional,
        tag="선택",
    )

    domain_header("직무역량", f"현재 대상에 적용 가능한 {len(job_rows)}개 · 최대 {MAX_JOB_FUNCTION}개")
    job_selected = _render_competency_cards(
        job_rows,
        key_prefix="optional",
        disabled_codes=disabled_optional,
        tag="선택",
    )

optional_selected = sanitize_selection(specialty_selected + job_selected, competencies, target_level)
selection_issues = selection_errors(optional_selected, competencies)
if selection_issues:
    for issue in selection_issues:
        st.error(issue)

selected = base_codes + optional_selected
selected_rows = [row_by_code[code] for code in selected]
item_count = len(questions_for_factors(selected)) if selected else 0
estimated_minutes = max(1, round(item_count * 15 / 60))
summary_strip(
    (
        (f"{len(selected)}개", "측정역량"),
        (f"{item_count}문항", "예상 문항"),
        (f"약 {estimated_minutes}분", "예상시간"),
        (f"{len(optional_selected)}/{MAX_OPTIONAL}개", "선택역량"),
    )
)

overlaps: dict[str, list[str]] = defaultdict(list)
for row in selected_rows:
    if row["overlap_group"]:
        overlaps[row["overlap_group"]].append(row["factor_name_ko"])
overlap_warnings = [names for names in overlaps.values() if len(names) > 1]
if overlap_warnings:
    st.warning("내용이 겹칠 수 있는 동시 선택: " + " / ".join(", ".join(names) for names in overlap_warnings))

with st.container(border=True):
    st.markdown('<h3 class="tap-card-title">4. 목표와 추천 입력</h3>', unsafe_allow_html=True)
    st.markdown(
        '<p class="tap-card-sub">낮은 점수만으로 추천하지 않도록 조직 중요도와 학습희망을 체크합니다.</p>',
        unsafe_allow_html=True,
    )
    target_mean = st.slider(
        "조직 기대 행동빈도(1~5)",
        1.0,
        5.0,
        3.5,
        0.1,
        help="파일럿 전 임시 운영값입니다. 실제 운영에서는 직무분석과 전문가 합의로 역량·대상별 목표를 정하세요.",
    )
    st.caption("목표 3.5는 표준이나 규준이 아니라 교육 우선순위 대화를 위한 임시 설정값입니다.")

    selected_factor_rows = [row_by_code[code] for code in selected]
    domain_header("조직 우선역량", "최대 3개 · 교육담당자 설정")
    organization_priorities = _render_limited_factor_checkboxes(
        selected_factor_rows,
        key_prefix="priority",
        previous=list(st.session_state.organization_priorities),
        limit=min(3, len(selected_factor_rows)),
    )

    domain_header("학습 희망역량", "최대 3개 · 데모에서는 참여자 선택을 미리 설정")
    learner_interests = _render_limited_factor_checkboxes(
        selected_factor_rows,
        key_prefix="interest",
        previous=list(st.session_state.learner_interests),
        limit=min(3, len(selected_factor_rows)),
    )

    training_cause = st.radio(
        "현재 격차의 주된 원인",
        options=["knowledge_skill", "mixed_or_unknown", "system_only"],
        format_func={
            "knowledge_skill": "지식·기술·연습 부족",
            "mixed_or_unknown": "혼합 또는 아직 확인되지 않음",
            "system_only": "권한·도구·프로세스 등 시스템 요인",
        }.get,
        horizontal=True,
    )
    delivery_preference = st.radio(
        "선호 교육방식",
        options=["all", "offline", "online"],
        format_func={"all": "무관", "offline": "집합", "online": "온라인"}.get,
        horizontal=True,
    )

if training_cause == "system_only":
    callout(
        "교육 추천 중단",
        "시스템 요인이 주된 원인이므로 비교육적 개선을 우선 제안합니다.",
        icon="!",
        tone="warn",
    )

date_error = end_date < start_date
if date_error:
    st.error("응답 마감일은 시작일보다 빠를 수 없습니다.")

if st.button(
    "설정 저장 후 참여자 화면 확인",
    type="primary",
    disabled=item_count == 0 or bool(selection_issues) or date_error,
    width="stretch",
):
    st.session_state.project_name = project_name.strip() or "이름 없는 진단 프로젝트"
    st.session_state.project_start_date = start_date.isoformat()
    st.session_state.project_end_date = end_date.isoformat()
    st.session_state.target_level = target_level
    st.session_state.selected_factors = selected
    st.session_state.target_means = {code: target_mean for code in selected}
    st.session_state.organization_priorities = organization_priorities
    st.session_state.learner_interests = learner_interests
    st.session_state.training_cause = training_cause
    st.session_state.delivery_preference = delivery_preference
    reset_assessment(st.session_state)
    st.switch_page("pages/2_assessment.py")
