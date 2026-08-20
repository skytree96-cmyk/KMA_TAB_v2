from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
import hashlib
import secrets

import streamlit as st

from tap.runtime_guard import stop_on_stale


stop_on_stale(
    st,
    ("tap.company_scope_ui", "tap.github_demo_store", "tap.tenant", "tap.ui"),
)

from tap.data import load_competencies, questions_for_factors
from tap.company_scope_ui import (
    company_admin_code_from_page,
    company_registration_code_from_page,
    render_company_scope_gate,
)
from tap.github_demo_store import (
    DemoStoreConfig,
    GitHubDemoStore,
    project_payload_from_state,
)
from tap.selection import (
    MAX_JOB_FUNCTION,
    MAX_OPTIONAL,
    MAX_SPECIALTY,
    applicable_to_level,
    sanitize_selection,
    selection_errors,
)
from tap.state import (
    PARTICIPANT_ID_WIDGET_KEY,
    activate_assessment_phase,
    ensure_state,
    reset_all_assessments,
)
from tap.tenant import verify_company_access_code
from tap.ui import callout, domain_header, page_header, setup_page, summary_strip


setup_page("교육평가 프로젝트", "T")
ensure_state(st.session_state)
competencies = load_competencies()
row_by_code = {row["factor_code"]: row for row in competencies}

level_labels = {"staff": "실무자", "manager": "관리자·리더", "executive": "임원"}
COMPANY_SCOPE_KEY = "project_setup"
PROJECT_WRITE_ACCESS_CODE_WIDGET_KEY = "_project_setup_company_write_access_code"


def _save_project_to_demo_store() -> None:
    """Publish one project snapshot without making GitHub a hard dependency."""

    try:
        config = DemoStoreConfig.from_sources(st.secrets)
    except Exception as exc:  # pragma: no cover - defensive config boundary
        st.session_state["demo_store_project_pending"] = True
        st.session_state["demo_store_notice"] = {
            "level": "error",
            "message": f"GitHub 테스트 저장 설정을 확인하지 못했습니다({type(exc).__name__}). 현 세션의 프로젝트는 유지됩니다.",
        }
        return

    if not config.enabled:
        st.session_state["demo_store_project_pending"] = False
        st.session_state["demo_store_notice"] = {
            "level": "info",
            "message": "GitHub 테스트 저장소가 미설정되어 현재 브라우저 세션과 JSON 파일 방식으로 진행합니다.",
        }
        return
    company_access_code = str(
        st.session_state.get(PROJECT_WRITE_ACCESS_CODE_WIDGET_KEY)
        or company_admin_code_from_page(st.session_state, COMPANY_SCOPE_KEY)
        or ""
    ).strip()
    company_registration_code = company_registration_code_from_page(
        st.session_state, COMPANY_SCOPE_KEY
    )
    company_id = str(st.session_state.get("company_id") or "").strip()
    company_digest = str(
        st.session_state.get("company_access_digest") or ""
    ).strip()
    if not config.project_write_enabled:
        st.session_state["demo_store_project_pending"] = True
        st.session_state["demo_store_notice"] = {
            "level": "warning",
            "message": "GitHub 쓰기 토큰 또는 기업 관리자 확인코드가 미설정되어 테스트 프로젝트를 게시하지 못했습니다.",
        }
        return
    if not (
        company_id
        and company_digest
        and verify_company_access_code(
            company_id,
            company_access_code,
            company_digest,
            config.salt,
        )
    ):
        st.session_state["demo_store_project_pending"] = True
        st.session_state["demo_store_notice"] = {
            "level": "warning",
            "message": "현재 회사의 기업 관리자 확인코드를 다시 입력해 주세요. 참여자 접속코드와는 별도입니다.",
        }
        return

    try:
        GitHubDemoStore(
            config,
            company_access_code=company_access_code,
            company_registration_code=company_registration_code,
        ).save_project(
            project_payload_from_state(
                st.session_state,
                tenant_salt=config.salt,
            )
        )
    except Exception as exc:  # network/API failure must not discard the project
        st.session_state["demo_store_project_pending"] = True
        st.session_state["demo_store_notice"] = {
            "level": "error",
            "message": f"GitHub 테스트 프로젝트 저장에 실패했습니다({type(exc).__name__}). 현 세션은 유지되며 검사 화면에서 다시 시도할 수 있습니다.",
        }
        return

    st.session_state["demo_store_project_pending"] = False
    st.session_state["demo_store_notice"] = {
        "level": "success",
        "message": (
            f"{st.session_state.get('company_name', '현재 회사')} 범위에 테스트 프로젝트를 저장했습니다. "
            f"기업 ID: {company_id} · 프로젝트 코드: {st.session_state.get('project_id', '')}"
        ),
    }


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
    "교육평가 프로젝트 만들기",
    "교육 전·후 역량평가 설계",
    "같은 참여자의 교육 전 기준선과 교육 후 변화를 비교할 수 있도록 일정과 측정역량을 고정합니다.",
    badge="사전·사후 비교",
)

try:
    project_store_config = DemoStoreConfig.from_sources(st.secrets)
except Exception as exc:
    project_store_config = None
    st.error(
        f"기업 범위 설정을 확인하지 못했습니다({type(exc).__name__}). "
        "KMA 관리자에게 저장소 설정을 확인해 주세요."
    )

company_scope_ready = False
if project_store_config is not None and project_store_config.enabled:
    company_scope = render_company_scope_gate(
        st,
        project_store_config,
        key_prefix=COMPANY_SCOPE_KEY,
        heading="1. 프로젝트를 관리할 회사 확인",
    )
    company_scope_ready = bool(company_scope.verified and company_scope.company_id)
else:
    st.warning(
        "기업 분리 저장소가 활성화되지 않아 새 프로젝트를 저장할 수 없습니다. "
        "기획검증 배포 설정을 확인해 주세요."
    )

if not company_scope_ready:
    st.info("기업 범위를 확인하면 해당 회사에 속한 프로젝트만 생성·저장됩니다.")

project_write_ready = False
if company_scope_ready and project_store_config is not None:
    if PROJECT_WRITE_ACCESS_CODE_WIDGET_KEY not in st.session_state:
        # Copy only between disposable page widgets; the raw code never enters
        # canonical state or a project payload.
        st.session_state[PROJECT_WRITE_ACCESS_CODE_WIDGET_KEY] = (
            company_admin_code_from_page(st.session_state, COMPANY_SCOPE_KEY)
        )
    project_write_code = st.text_input(
        "프로젝트 저장용 기업 관리자 확인코드",
        type="password",
        key=PROJECT_WRITE_ACCESS_CODE_WIDGET_KEY,
        help="현재 회사에 새 프로젝트를 쓰기 전에 다시 확인합니다. 원문은 저장하지 않습니다.",
    )
    project_write_ready = bool(
        project_store_config.project_write_enabled
        and verify_company_access_code(
            company_scope.company_id,
            project_write_code,
            company_scope.access_digest,
            project_store_config.salt,
        )
    )
    if project_write_code and not project_write_ready:
        st.warning("현재 회사의 기업 관리자 확인코드가 일치하지 않습니다.")
    elif project_write_ready:
        st.caption("기업 관리자 확인 완료 · 이 회사 범위에만 프로젝트가 저장됩니다.")

with st.container(border=True):
    st.markdown('<h3 class="tap-card-title">2. 교육과 검사 일정</h3>', unsafe_allow_html=True)
    st.markdown(
        '<p class="tap-card-sub">교육과정·교육일·사전/사후 검사 기간을 먼저 고정합니다. 최근 8주 회상기간이 교육 전을 포함하지 않도록 사후검사는 교육 8~10주 후를 권장합니다.</p>',
        unsafe_allow_html=True,
    )
    _initialize_checkbox("project_name_input_initialized", True)
    if "project_name_input" not in st.session_state:
        st.session_state.project_name_input = st.session_state.project_name
    project_name = st.text_input("프로젝트명", key="project_name_input")

    if "course_name_input" not in st.session_state:
        st.session_state.course_name_input = st.session_state.get("course_name", "신임 리더 실행력 향상 과정")
    course_name = st.text_input("교육과정명", key="course_name_input")

    level_codes = list(level_labels)
    target_level = st.radio(
        "응답 대상",
        options=level_codes,
        format_func=level_labels.get,
        index=level_codes.index(st.session_state.target_level),
        horizontal=True,
        key="target_level_picker",
    )

    default_pre_start = _iso_date(
        st.session_state.get("pre_start_date", st.session_state.project_start_date),
        date.today() + timedelta(days=7),
    )
    default_pre_end = _iso_date(
        st.session_state.get("pre_end_date", st.session_state.project_end_date),
        default_pre_start + timedelta(days=11),
    )
    default_training_date = _iso_date(
        st.session_state.get("training_date"),
        default_pre_end + timedelta(days=3),
    )
    default_post_start = _iso_date(
        st.session_state.get("post_start_date"),
        default_training_date + timedelta(weeks=8),
    )
    default_post_end = _iso_date(
        st.session_state.get("post_end_date"),
        default_post_start + timedelta(days=11),
    )

    training_date = st.date_input("교육일", value=default_training_date, key="training_date_picker")
    pre_left, pre_right = st.columns(2)
    with pre_left:
        pre_start_date = st.date_input("교육 전 검사 시작일", value=default_pre_start, key="pre_start_picker")
    with pre_right:
        pre_end_date = st.date_input("교육 전 검사 마감일", value=default_pre_end, key="pre_end_picker")
    post_left, post_right = st.columns(2)
    with post_left:
        post_start_date = st.date_input("교육 후 검사 시작일", value=default_post_start, key="post_start_picker")
    with post_right:
        post_end_date = st.date_input("교육 후 검사 마감일", value=default_post_end, key="post_end_picker")

    # 검사 단계는 별도 사이드바 메뉴에서 선택한다. 프로젝트 스냅샷에는
    # 하위 버전 호환을 위해 pre를 기록하고 실제 진입 페이지가 단계를 정한다.
    current_phase = "pre"
    st.info(
        "검사 단계 선택은 왼쪽 메뉴의 ‘교육 전 검사’와 ‘교육 후 검사’에서 합니다. "
        "프로젝트 저장 후에는 교육 전 검사로 이동합니다."
    )
    allow_schedule_override = st.checkbox(
        "공개 시연에서 검사기간 예외 허용",
        value=bool(st.session_state.get("allow_schedule_override", True)),
        help="시연 중에는 설정 기간 밖에서도 실제 검사를 제출할 수 있습니다. 운영 전환 시에는 해제하세요.",
    )

base_rows = [
    row for row in competencies if row["active_for_scoring"] and row["library_type"] == "base"
]
applicable_base = [row for row in base_rows if applicable_to_level(row, target_level)]
base_codes = [row["factor_code"] for row in applicable_base]

with st.container(border=True):
    st.markdown('<h3 class="tap-card-title">3. 기본역량</h3>', unsafe_allow_html=True)
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
    st.markdown('<h3 class="tap-card-title">4. 선택역량</h3>', unsafe_allow_html=True)
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
    st.markdown('<h3 class="tap-card-title">5. 목표와 추천 입력</h3>', unsafe_allow_html=True)
    st.markdown(
        '<p class="tap-card-sub">낮은 점수만으로 추천하지 않도록 조직 중요도와 학습희망을 체크합니다.</p>',
        unsafe_allow_html=True,
    )
    target_mean = st.slider(
        "조직 기대 행동빈도(1~5)",
        1.0,
        5.0,
        float(
            next(iter(dict(st.session_state.get("target_means") or {}).values()), 3.5)
        ),
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

    # 격차 원인은 사전점수만으로 판정할 수 없으며 프로젝트 생성자가 미리
    # 단정하면 추천과 사후해석에 확인편향이 생길 수 있다. 생성 단계에서는
    # 중립값을 저장하고 교육 후 현업전이 응답과 함께 해석한다.
    training_cause = "mixed_or_unknown"
    callout(
        "격차 원인은 교육 후에 확인",
        "프로젝트 생성 시 원인을 미리 단정하지 않습니다. 교육 전·후 변화와 적용 기회, 상사 지원, 도구·권한, 시간·프로세스 응답을 함께 확인하세요.",
        icon="i",
    )
    delivery_preference = st.radio(
        "선호 교육방식",
        options=["all", "offline", "online"],
        index=["all", "offline", "online"].index(
            str(st.session_state.get("delivery_preference", "all"))
            if str(st.session_state.get("delivery_preference", "all"))
            in {"all", "offline", "online"}
            else "all"
        ),
        format_func={"all": "무관", "offline": "집합", "online": "온라인"}.get,
        horizontal=True,
    )

date_errors: list[str] = []
if pre_end_date < pre_start_date:
    date_errors.append("교육 전 검사 마감일은 시작일보다 빠를 수 없습니다.")
if post_end_date < post_start_date:
    date_errors.append("교육 후 검사 마감일은 시작일보다 빠를 수 없습니다.")
if pre_end_date >= training_date:
    date_errors.append("교육 전 검사는 교육일 전에 마감해야 합니다.")
if post_start_date <= training_date:
    date_errors.append("교육 후 검사는 교육일 다음 날 이후에 시작해야 합니다.")
for message in date_errors:
    st.error(message)

post_delay_days = (post_start_date - training_date).days
if not date_errors and not 56 <= post_delay_days <= 70:
    st.warning(
        f"현재 사후검사는 교육 {post_delay_days}일 후 시작합니다. "
        "최근 8주 행동에 교육 전 기간이 섞이지 않도록 교육 8~10주(56~70일) 후를 권장합니다."
    )

if st.button(
    "설정 저장 후 교육 전 검사 시작",
    type="primary",
    disabled=(
        not company_scope_ready
        or not project_write_ready
        or item_count == 0
        or bool(selection_issues)
        or bool(date_errors)
    ),
    width="stretch",
):
    next_project_name = project_name.strip() or "이름 없는 교육평가 프로젝트"
    next_course_name = course_name.strip() or "이름 없는 교육과정"
    next_schedule = (
        training_date.isoformat(),
        pre_start_date.isoformat(),
        pre_end_date.isoformat(),
        post_start_date.isoformat(),
        post_end_date.isoformat(),
    )
    stored_schedule = (
        str(st.session_state.get("training_date", "")),
        str(st.session_state.get("pre_start_date", "")),
        str(st.session_state.get("pre_end_date", "")),
        str(st.session_state.get("post_start_date", "")),
        str(st.session_state.get("post_end_date", "")),
    )
    has_saved_assessment = any(
        bool(value)
        for value in dict(st.session_state.get("responses_by_phase") or {}).values()
    )
    selection_changed = (
        set(st.session_state.get("selected_factors", [])) != set(selected)
        or st.session_state.get("target_level") != target_level
        or (
            has_saved_assessment
            and (
                str(st.session_state.get("project_name", "")) != next_project_name
                or str(st.session_state.get("course_name", "")) != next_course_name
                or stored_schedule != next_schedule
            )
        )
    )
    project_identity_changed = (
        set(st.session_state.get("selected_factors", [])) != set(selected)
        or st.session_state.get("target_level") != target_level
        or str(st.session_state.get("project_name", "")) != next_project_name
        or str(st.session_state.get("course_name", "")) != next_course_name
        or stored_schedule != next_schedule
    )
    st.session_state.project_name = next_project_name
    if project_identity_changed or not str(st.session_state.get("project_id", "")).strip():
        # A random code prevents two independently created but identically
        # configured synthetic projects from being merged in the data branch.
        st.session_state.project_id = "TAP-" + secrets.token_hex(8).upper()
    st.session_state.course_name = next_course_name
    st.session_state.training_date = training_date.isoformat()
    st.session_state.pre_start_date = pre_start_date.isoformat()
    st.session_state.pre_end_date = pre_end_date.isoformat()
    st.session_state.post_start_date = post_start_date.isoformat()
    st.session_state.post_end_date = post_end_date.isoformat()
    # 기존 화면과 내보내기 형식을 위해 프로젝트 기간은 사전검사 기간을 가리킨다.
    st.session_state.project_start_date = pre_start_date.isoformat()
    st.session_state.project_end_date = pre_end_date.isoformat()
    st.session_state.target_level = target_level
    st.session_state.selected_factors = selected
    st.session_state.target_means = {code: target_mean for code in selected}
    st.session_state.organization_priorities = organization_priorities
    st.session_state.learner_interests = learner_interests
    st.session_state.training_cause = training_cause
    st.session_state.delivery_preference = delivery_preference
    st.session_state.allow_schedule_override = allow_schedule_override

    ordered_questions = sorted(
        questions_for_factors(selected),
        key=lambda row: hashlib.sha256(
            f"{project_name.strip() or 'TAP'}|{row['question_code']}".encode("utf-8")
        ).hexdigest(),
    )
    snapshot_rows = sorted(
        (
            str(row["question_code"]),
            str(row["revised_text"]),
            str(row.get("scoring_direction", "direct")),
        )
        for row in ordered_questions
    )
    snapshot_payload = "\n".join("|".join(parts) for parts in snapshot_rows)
    new_snapshot_hash = hashlib.sha256(snapshot_payload.encode("utf-8")).hexdigest()
    existing_snapshot_hash = str(st.session_state.get("question_snapshot_hash", ""))
    if existing_snapshot_hash and existing_snapshot_hash != new_snapshot_hash:
        selection_changed = True
    if selection_changed or not existing_snapshot_hash:
        st.session_state.question_snapshot_hash = new_snapshot_hash
        st.session_state.question_snapshot_codes = [str(row["question_code"]) for row in ordered_questions]
        st.session_state.assessment_version = f"TAP-1.0+{new_snapshot_hash[:12]}"

    # 측정역량이 바뀌면 동일 문항 조건이 깨지므로 양 시점 응답을 함께 초기화한다.
    # 검사 단계만 pre→post로 바꾸는 경우에는 사전응답을 유지한다.
    if selection_changed:
        reset_all_assessments(st.session_state)
    if project_identity_changed:
        # A pseudonymous participant ID belongs to one project pairing only.
        # Clear both the durable value and its disposable widget key whenever
        # the project identity changes; a pre→post phase switch alone does not
        # enter this branch and therefore keeps the pairing ID.
        st.session_state.participant_id = ""
        st.session_state.pop(PARTICIPANT_ID_WIDGET_KEY, None)
    activate_assessment_phase(st.session_state, current_phase)
    st.session_state.current_assessment_phase = current_phase
    _save_project_to_demo_store()
    st.switch_page("pages/7_pre_assessment.py")
