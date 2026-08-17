from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

import pandas as pd
import streamlit as st

from tap.runtime_guard import stop_on_stale


stop_on_stale(
    st,
    ("tap.dashboard", "tap.github_demo_store", "tap.radar", "tap.ui"),
)

from tap.aggregation import aggregate_factor_results
from tap.config import DATA_DIR, MIN_GROUP_N
from tap.dashboard import (
    build_persistent_dashboard,
    completed_store_submission_factor_rows,
    fetch_store_snapshot,
    normalize_target_means,
)
from tap.data import load_competencies, questions_for_factors
from tap.github_demo_store import DemoStoreConfig, DemoStoreError, GitHubDemoStore
from tap.radar import build_planning_preview_radar, build_pre_post_radar
from tap.reporting import (
    build_organization_report_model,
    build_pre_post_group_summary,
    completed_session_factor_rows,
    organization_report_fragment,
    prepare_group_results,
    printable_organization_report_html,
    read_group_results_csv,
)
from tap.state import (
    DEMO_STORE_ACCESS_CODE_KEY,
    DEMO_STORE_REPORT_PREVIEW_CODE_KEY,
    DEMO_STORE_REPORT_PREVIEW_CODE_WIDGET_KEY,
    ensure_state,
    load_demo_store_report_preview_code_widget,
    save_demo_store_report_preview_code_widget,
)
from tap.ui import callout, page_header, setup_page


setup_page("교육 전후 리포트", "4")
ensure_state(st.session_state)


@st.cache_data(ttl=30, show_spinner=False)
def _read_store_snapshot(_secrets: object) -> dict[str, object]:
    config = DemoStoreConfig.from_sources(secrets=_secrets)
    store = GitHubDemoStore(config)
    status = store.status()
    if not status["read_enabled"]:
        return {"status": status, "projects": [], "submissions": []}
    return {
        "status": status,
        **fetch_store_snapshot(store),
    }


page_header(
    "교육 전후 리포트",
    "조직 교육 전후 리포트",
    "교육 전·후 자료가 있으면 같은 참여자의 변화를, 단일시점 자료이면 교육수요를 보여줍니다.",
    badge=f"짝지어진 참여자 N≥{MIN_GROUP_N}만 공개",
)
callout(
    "개인 순위와 단정적 교육효과는 제공하지 않습니다",
    "전후 비교는 동일 교육 참여자 ID로 짝지은 자기보고 변화이며, 비교집단이 없으면 교육의 인과효과로 확정하지 않습니다.",
    icon="5+",
)

template_csv = """participant_id,factor_code,score_1_to_5,project_id,assessment_version,target_level,assessment_date,session_type,valid_items,na_items,missing_items,opportunity_1_to_5,manager_support_1_to_5,resource_support_1_to_5,time_process_support_1_to_5
P001,CORE-CO,3.0,PROJECT-001,TAP-1.0,manager,2026-08-01,pre,4,0,0,,,,
P001,CORE-CO,3.8,PROJECT-001,TAP-1.0,manager,2026-10-01,post,4,0,0,4,4,3,4
P002,CORE-CO,3.2,PROJECT-001,TAP-1.0,manager,2026-08-01,pre,3,1,0,,,,
P002,CORE-CO,3.7,PROJECT-001,TAP-1.0,manager,2026-10-01,post,4,0,0,3,4,4,3
"""

completed_dates = dict(st.session_state.get("assessment_completed_at_by_phase") or {})
current_project_id = str(st.session_state.get("project_id") or "").strip()
current_questions = questions_for_factors(
    list(st.session_state.get("selected_factors", []))
)
session_rows = completed_session_factor_rows(
    current_questions,
    dict(st.session_state.get("responses_by_phase") or {}),
    dict(st.session_state.get("assessment_completed_by_phase") or {}),
    participant_id=str(st.session_state.get("participant_id", "")),
    project_id=str(
        st.session_state.get("project_id")
        or st.session_state.get("project_name", "TAP-PROJECT")
    ),
    assessment_version=str(st.session_state.get("assessment_version", "TAP-1.0")),
    target_level=str(st.session_state.get("target_level", "staff")),
    assessment_dates={
        "pre": completed_dates.get("pre") or st.session_state.get("pre_end_date", ""),
        "post": completed_dates.get("post") or st.session_state.get("post_end_date", ""),
    },
    target_means=dict(st.session_state.get("target_means") or {}),
    post_transfer_responses=dict(st.session_state.get("post_transfer_responses") or {}),
)

try:
    demo_store_secrets: object = dict(st.secrets)
except Exception:  # No secrets file is the normal local-development state.
    demo_store_secrets = {}

stored: dict[str, object] = {"status": {}, "projects": [], "submissions": []}
store_error = ""
try:
    stored = _read_store_snapshot(demo_store_secrets)
except DemoStoreError as exc:
    store_error = str(exc)

stored_projects = list(stored.get("projects") or [])
stored_submissions = list(stored.get("submissions") or [])
stored_dashboard = build_persistent_dashboard(stored_submissions, stored_projects)
stored_overviews = {
    str(row["project_id"]): row for row in stored_dashboard["projects"]
}

st.markdown("### 실시 프로젝트에서 리포트 열기")
st.caption(
    "GitHub 기획검증 저장소에 누적된 프로젝트를 선택하면 완료 결과를 바로 불러옵니다. "
    "개별 참여자 원문 ID와 개인점수는 표시하지 않습니다."
)

project_choices: dict[str, dict[str, object]] = {}
for project_id, row in stored_overviews.items():
    project_choices[f"store:{project_id}"] = {
        "kind": "store",
        "project_id": project_id,
        "name": str(row.get("name") or project_id),
        "pre": int(row.get("pre_completed") or 0),
        "post": int(row.get("post_completed") or 0),
        "paired": int(row.get("completed") or 0),
        "status": str(row.get("status") or "검사 대기"),
    }

session_completed = dict(st.session_state.get("assessment_completed_by_phase") or {})
session_project_id = (
    current_project_id
    or (
        str(st.session_state.get("project_name") or "TAP-PROJECT")
        if session_rows
        else ""
    )
)
if session_project_id:
    session_choice_key = f"session:{session_project_id}"
    project_choices[session_choice_key] = {
        "kind": "session",
        "project_id": session_project_id,
        "name": str(st.session_state.get("project_name") or session_project_id),
        "pre": int(bool(session_completed.get("pre"))),
        "post": int(bool(session_completed.get("post"))),
        "paired": int(bool(session_completed.get("pre") and session_completed.get("post"))),
        "status": "현재 브라우저",
    }

project_keys = list(project_choices)
preferred_store_key = f"store:{current_project_id}" if current_project_id else ""
preferred_session_key = f"session:{session_project_id}" if session_project_id else ""
default_project_key = (
    preferred_store_key
    if preferred_store_key in project_choices
    else preferred_session_key
    if preferred_session_key in project_choices
    else project_keys[0]
    if project_keys
    else ""
)
choice_state_key = "organization_report_project_choice"
if project_keys and st.session_state.get(choice_state_key) not in project_choices:
    st.session_state[choice_state_key] = default_project_key

selected_project_key = ""
if project_keys:
    select_col, refresh_col = st.columns([4, 1])
    with select_col:
        selected_project_key = st.selectbox(
            "프로젝트 선택",
            project_keys,
            key=choice_state_key,
            format_func=lambda key: (
                f"{project_choices[key]['name']} · {project_choices[key]['project_id']} · "
                f"교육 전 {project_choices[key]['pre']}명 / 교육 후 {project_choices[key]['post']}명"
                + (" · 현재 브라우저" if project_choices[key]["kind"] == "session" else "")
            ),
        )
    with refresh_col:
        st.write("")
        if st.button("프로젝트 새로고침", width="stretch"):
            _read_store_snapshot.clear()
            st.rerun()

    selected_overview = project_choices[selected_project_key]
    with st.container(border=True):
        st.markdown(f"**{selected_overview['name']}**")
        st.caption(
            f"프로젝트 코드 {selected_overview['project_id']} · {selected_overview['status']}"
        )
        pre_col, post_col, pair_col = st.columns(3)
        pre_col.metric("교육 전 완료", f"{selected_overview['pre']}명")
        post_col.metric("교육 후 완료", f"{selected_overview['post']}명")
        pair_col.metric("전·후 짝지음", f"{selected_overview['paired']}명")
else:
    st.info(
        "저장된 실시 프로젝트가 없습니다. 현재 브라우저에서 프로젝트를 만들고 검사를 완료하면 여기에 표시됩니다."
    )

if store_error:
    st.warning(f"GitHub 누적 프로젝트를 읽지 못했습니다: {store_error}")

CSV_UPLOAD_KEY = "organization_report_csv_upload"
CSV_USE_KEY = "organization_report_use_csv"
CSV_SAMPLE_KEY = "organization_report_show_sample"
SMALL_N_PREVIEW_SCOPE_KEY = "organization_report_small_n_preview_scope"
SMALL_N_PREVIEW_TOGGLE_PREFIX = "organization_report_small_n_preview_enabled"
SMALL_N_PREVIEW_AXES_PREFIX = "organization_report_small_n_preview_axes"
SMALL_N_PREVIEW_LOCK_KEY = "organization_report_small_n_preview_locked"
PUBLIC_RADAR_AXES_PREFIX = "organization_report_public_radar_axes"


def _project_widget_key(prefix: str, project_key: str) -> str:
    """Return a stable widget key without exposing the selected project code."""

    import hashlib

    suffix = hashlib.sha256(project_key.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{suffix}"


def _save_report_preview_code_and_unlock(state: MutableMapping[str, Any]) -> None:
    """Only an explicit preview-code edit unlocks a locked browser session."""

    save_demo_store_report_preview_code_widget(state)
    state[SMALL_N_PREVIEW_LOCK_KEY] = False


def _ordered_preview_rows(
    rows: list[dict[str, object]], selected_factors: list[object]
) -> list[dict[str, object]]:
    """Keep valid comparison rows in the project's fixed competency order."""

    by_code = {
        str(row.get("factor_code") or ""): row
        for row in rows
        if row.get("pre_mean") is not None
        and row.get("post_mean") is not None
        and int(row.get("paired_n") or 0) >= 1
    }
    ordered: list[dict[str, object]] = []
    seen: set[str] = set()
    for code in (str(value) for value in selected_factors):
        if code in by_code and code not in seen:
            ordered.append(by_code[code])
            seen.add(code)
    return ordered


def _render_csv_tools() -> None:
    st.markdown("### 파일로 직접 비교하기")
    with st.expander("CSV 파일로 직접 비교하기 · 보조 기능", expanded=False):
        st.caption(
            "기본 자료는 위에서 선택한 실시 프로젝트입니다. ‘업로드 CSV로 리포트 보기’를 켠 경우에만 "
            "CSV가 선택 프로젝트보다 우선합니다. 같은 참여자는 pre/post에서 동일 participant_id를 사용하세요. "
            "공개 데모에는 실제 개인정보나 기밀자료를 업로드하지 마세요."
        )
        download_col, upload_col = st.columns([1, 2])
        with download_col:
            st.download_button(
                "사전·사후 CSV 양식",
                template_csv.encode("utf-8-sig"),
                "tap_pre_post_group_result_template.csv",
                "text/csv",
                width="stretch",
            )
        with upload_col:
            current_upload = st.file_uploader(
                "교육 참여자 조직결과 CSV",
                type=["csv"],
                key=CSV_UPLOAD_KEY,
                help=(
                    "필수: participant_id, factor_code, score_1_to_5, project_id, "
                    "assessment_version, target_level, assessment_date. 전후 비교 시 session_type도 필요합니다."
                ),
            )
        st.checkbox(
            "업로드 CSV로 리포트 보기",
            value=False,
            key=CSV_USE_KEY,
            disabled=current_upload is None,
            help="선택한 경우에만 업로드 CSV를 우선 자료로 사용합니다.",
        )
        st.checkbox(
            "예시 리포트 보기",
            value=False,
            key=CSV_SAMPLE_KEY,
            help="실제 완료 결과나 선택한 CSV가 없을 때만 화면 확인용 합성 예시를 표시합니다.",
        )


uploaded = st.session_state.get(CSV_UPLOAD_KEY)
use_uploaded = bool(st.session_state.get(CSV_USE_KEY, False))
show_sample = bool(st.session_state.get(CSV_SAMPLE_KEY, False))

source_kind = ""
is_sample = False
source = pd.DataFrame()
store_rows: list[dict[str, object]] = []
store_validation_warnings: list[str] = []
stored_project: dict[str, object] = {}
stored_target_means: dict[str, float] = {}
store_project_code = ""

if uploaded is not None and use_uploaded:
    source_kind = "upload"
    try:
        source = read_group_results_csv(uploaded.getvalue())
    except ValueError as exc:
        st.error(str(exc))
        _render_csv_tools()
        st.stop()
    st.success("업로드 CSV를 명시적으로 선택해 실제 조직결과를 사용하고 있습니다.")
elif selected_project_key:
    selected_choice = project_choices[selected_project_key]
    store_project_code = str(selected_choice["project_id"])
    if selected_choice["kind"] == "store":
        stored_project = next(
            (
                row
                for row in stored_projects
                if str(row.get("project_id") or "") == store_project_code
            ),
            {},
        )
        stored_factors = list(stored_project.get("selected_factors") or [])
        stored_questions = questions_for_factors([str(code) for code in stored_factors])
        if not stored_project:
            store_validation_warnings.append(
                f"프로젝트 코드 {store_project_code}의 저장된 프로젝트 설정을 찾지 못했습니다."
            )
        elif not stored_questions:
            store_validation_warnings.append(
                f"프로젝트 코드 {store_project_code}에 집계 가능한 측정역량이 없습니다."
            )
        else:
            stored_target_means = normalize_target_means(
                stored_project.get("target_means"),
                warnings=store_validation_warnings,
            )
            store_rows = completed_store_submission_factor_rows(
                stored_submissions,
                stored_questions,
                project_id=store_project_code,
                assessment_version=str(
                    stored_project.get("assessment_version") or "TAP-1.0"
                ),
                target_level=str(stored_project.get("target_level") or "staff"),
                target_means=stored_target_means,
                question_snapshot_hash=str(
                    stored_project.get("question_snapshot_hash") or ""
                ),
                warnings=store_validation_warnings,
            )
        if store_rows:
            source_kind = "store"
            source = pd.DataFrame(store_rows)
            stored_participants = int(source["participant_id"].nunique())
            st.success(
                f"선택한 프로젝트의 GitHub 누적 완료결과 {stored_participants}명을 사용하고 있습니다. "
                "참여자 연결에는 원문 ID가 아닌 프로젝트별 가명키를 사용합니다."
            )
        elif current_project_id == store_project_code and session_rows:
            source_kind = "session"
            source = pd.DataFrame(session_rows)
            st.info(
                "선택 프로젝트의 누적 완료결과가 없어 현재 브라우저에서 완료한 실제 결과로 대체했습니다."
            )
    elif session_rows:
        source_kind = "session"
        source = pd.DataFrame(session_rows)

if source_kind == "session" and not source.empty:
    completed_phases = sorted(set(source["session_type"]))
    phase_text = "교육 전·후" if completed_phases == ["post", "pre"] else (
        "교육 전" if completed_phases == ["pre"] else "교육 후"
    )
    st.success(f"현재 브라우저에서 완료한 실제 {phase_text} 결과를 사용하고 있습니다.")

for warning in store_validation_warnings:
    st.warning(warning)

if not source_kind and show_sample:
    source_kind = "sample"
    is_sample = True
    base_sample = pd.read_csv(DATA_DIR / "sample_group_results.csv")
    # 기존 단일시점 예시를 화면 확인용 전후 예시로 확장한다. 모든 값은 예시임을 명시한다.
    pre_sample = base_sample.copy()
    pre_sample["session_type"] = "pre"
    pre_sample["score_1_to_5"] = (pre_sample["score_1_to_5"] - 0.3).clip(lower=1.0).round(2)
    post_sample = base_sample.copy()
    post_sample["session_type"] = "post"
    participant_ids = sorted(post_sample["participant_id"].astype(str).unique())
    if len(participant_ids) > MIN_GROUP_N:
        post_sample = post_sample[post_sample["participant_id"].astype(str) != participant_ids[-1]].copy()
    for frame in (pre_sample, post_sample):
        frame["valid_items"] = 4
        frame["na_items"] = 0
        frame["missing_items"] = 0
    post_sample["opportunity_1_to_5"] = 3.8
    post_sample["manager_support_1_to_5"] = 3.6
    post_sample["resource_support_1_to_5"] = 3.4
    post_sample["time_process_support_1_to_5"] = 3.3
    source = pd.concat([pre_sample, post_sample], ignore_index=True)
    st.warning("예시 리포트 보기 옵션이 켜져 있습니다. 모든 수치와 변화량은 합성 예시이며 실제 결과가 아닙니다.")
elif not source_kind:
    st.info(
        "표시할 실제 결과가 없습니다. 선택한 프로젝트의 검사를 완료한 뒤 새로고침하거나, "
        "하단 보조 기능에서 CSV 또는 예시 리포트를 선택해 주세요."
    )
    if st.button("검사 진행하기", type="primary"):
        st.switch_page("pages/7_pre_assessment.py")
    _render_csv_tools()
    st.stop()

allow_report_schedule_override = (
    bool(stored_project.get("allow_schedule_override"))
    if source_kind == "store"
    else bool(st.session_state.get("allow_schedule_override"))
    if source_kind == "session"
    else False
)
clean, validation_errors, validation_warnings = prepare_group_results(
    source,
    load_competencies(),
    require_metadata=source_kind in {"session", "store", "upload"},
    allow_schedule_override=allow_report_schedule_override,
)
for warning in validation_warnings:
    st.warning(warning)
if validation_errors:
    for error in validation_errors:
        st.error(error)
    _render_csv_tools()
    st.stop()

session_values = set(clean["session_type"].dropna()) if "session_type" in clean.columns else set()
is_pre_post = {"pre", "post"}.issubset(session_values)
pre_post_summary = build_pre_post_group_summary(clean, min_group_n=MIN_GROUP_N) if is_pre_post else None

participant_count_for_privacy = (
    int(pre_post_summary["paired_participant_count"])
    if pre_post_summary
    else int(clean["participant_id"].nunique())
)
if source_kind in {"session", "store"} and participant_count_for_privacy < MIN_GROUP_N:
    result_scope = "현재 브라우저" if source_kind == "session" else "GitHub 누적 저장소"
    st.warning(
        f"{result_scope}에서 실제 완료 결과 {int(clean['participant_id'].nunique())}명의 데이터를 읽었습니다. "
        f"조직 리포트는 개인정보 보호를 위해 N≥{MIN_GROUP_N}일 때만 평균과 변화량을 공개합니다. "
        + (
            "본인의 실제 교육 전·후 수치는 개인 리포트에서 바로 확인할 수 있습니다."
            if source_kind == "session"
            else "참여자가 더 누적된 뒤 새로고침해 주세요."
        )
    )
    if source_kind == "session":
        if st.button("내 실제 교육 전·후 비교 보기", type="primary"):
            st.switch_page("pages/3_individual_report.py")

    small_n_preview_eligible = bool(
        source_kind == "store"
        and stored_project.get("demo_only") is True
        and is_pre_post
        and 1 <= participant_count_for_privacy < MIN_GROUP_N
    )
    if small_n_preview_eligible:
        preview_toggle_key = _project_widget_key(
            SMALL_N_PREVIEW_TOGGLE_PREFIX, selected_project_key
        )
        preview_axes_key = _project_widget_key(
            SMALL_N_PREVIEW_AXES_PREFIX, selected_project_key
        )
        previous_scope = str(st.session_state.get(SMALL_N_PREVIEW_SCOPE_KEY) or "")
        if previous_scope != selected_project_key:
            st.session_state[SMALL_N_PREVIEW_SCOPE_KEY] = selected_project_key
            st.session_state.pop(preview_toggle_key, None)
            st.session_state.pop(preview_axes_key, None)

        try:
            preview_config = DemoStoreConfig.from_sources(secrets=demo_store_secrets)
        except DemoStoreError:
            preview_config = DemoStoreConfig()

        with st.container(border=True):
            st.markdown("#### 소표본 기획검증 미리보기")
            st.caption(
                "테스트·기획 검토를 위한 화면 전용 기능입니다. 운영 리포트의 "
                f"N≥{MIN_GROUP_N} 공개 기준은 그대로 유지됩니다."
            )
            if (
                not preview_config.report_preview_code
                and not st.session_state.get(DEMO_STORE_REPORT_PREVIEW_CODE_KEY)
                and st.session_state.get(DEMO_STORE_ACCESS_CODE_KEY)
                and not st.session_state.get(SMALL_N_PREVIEW_LOCK_KEY)
            ):
                # 기존 배포 설정은 저장용 access_code 하나만 사용했습니다.
                # 별도 리포트 코드가 없는 경우에만 같은 세션의 확인값을 재사용합니다.
                st.session_state[DEMO_STORE_REPORT_PREVIEW_CODE_KEY] = str(
                    st.session_state[DEMO_STORE_ACCESS_CODE_KEY]
                )
            load_demo_store_report_preview_code_widget(st.session_state)
            st.text_input(
                "리포트 미리보기 코드",
                type="password",
                key=DEMO_STORE_REPORT_PREVIEW_CODE_WIDGET_KEY,
                on_change=_save_report_preview_code_and_unlock,
                args=(st.session_state,),
                help=(
                    "별도 리포트 미리보기 코드가 설정되면 그 코드를 사용하고, "
                    "미설정 시 기존 기획검증 접속코드를 사용합니다."
                ),
            )
            preview_granted = (
                not st.session_state.get(SMALL_N_PREVIEW_LOCK_KEY)
                and preview_config.report_preview_granted(
                    st.session_state.get(DEMO_STORE_REPORT_PREVIEW_CODE_KEY, "")
                )
            )
            if preview_granted and st.button(
                "미리보기 잠금",
                key=_project_widget_key("organization_report_preview_lock_button", selected_project_key),
                help="이 브라우저 세션에 남은 미리보기 코드를 지우고 소표본 값을 다시 숨깁니다.",
            ):
                st.session_state[DEMO_STORE_REPORT_PREVIEW_CODE_KEY] = ""
                st.session_state[preview_toggle_key] = False
                st.session_state[SMALL_N_PREVIEW_LOCK_KEY] = True
                st.rerun()
            preview_enabled = st.toggle(
                "소표본 실제값을 화면에서만 미리보기",
                value=False,
                key=preview_toggle_key,
                disabled=not preview_granted,
                help=(
                    "접속 권한을 확인한 뒤 직접 켜야 하며, 화면에는 기획검증용 워터마크가 표시됩니다."
                ),
            )
            if not preview_granted:
                st.caption(
                    "올바른 코드를 입력하기 전에는 소표본 평균·변화량을 계산하거나 표시하지 않습니다."
                )

        if preview_granted and preview_enabled:
            preview_summary = build_pre_post_group_summary(clean, min_group_n=1)
            ordered_preview_rows = _ordered_preview_rows(
                list(preview_summary["comparison_rows"]),
                list(stored_project.get("selected_factors") or []),
            )
            if not ordered_preview_rows:
                st.warning("선택 역량 중 전·후로 짝지을 수 있는 유효 결과가 없습니다.")
                st.stop()

            selected_preview_rows = ordered_preview_rows
            if len(ordered_preview_rows) > 8:
                factor_labels = {
                    str(row["factor_code"]): str(row["factor_name_ko"])
                    for row in ordered_preview_rows
                }
                selected_codes = st.multiselect(
                    "레이더에 표시할 역량 · 3~8개",
                    list(factor_labels),
                    default=list(factor_labels)[:8],
                    key=preview_axes_key,
                    max_selections=8,
                    format_func=lambda code: factor_labels[code],
                    help="프로젝트에 설정된 고정 순서에서 최대 8개를 선택합니다.",
                )
                selected_set = set(selected_codes)
                selected_preview_rows = [
                    row
                    for row in ordered_preview_rows
                    if str(row["factor_code"]) in selected_set
                ]
                if len(selected_preview_rows) < 3:
                    st.warning("N각형 레이더를 표시하려면 역량을 3개 이상 선택해 주세요.")
                    st.stop()

            st.warning(
                f"기획검증용 · 소표본 N={participant_count_for_privacy} · 외부 공유·캡처·인쇄 금지. "
                "교육효과 또는 조직 전체의 경향으로 해석하지 마세요."
            )
            pre_col, post_col, pair_col = st.columns(3)
            pre_col.metric("교육 전 참여", f"{preview_summary['pre_participant_count']}명")
            post_col.metric("교육 후 참여", f"{preview_summary['post_participant_count']}명")
            pair_col.metric("짝지어진 참여", f"{preview_summary['paired_participant_count']}명")

            preview_codes = [str(row["factor_code"]) for row in selected_preview_rows]
            preview_radar = build_planning_preview_radar(
                selected_preview_rows,
                paired_n=participant_count_for_privacy,
                preferred_codes=preview_codes,
                max_axes=min(8, len(selected_preview_rows)),
            )
            st.html(preview_radar["html"])
            if preview_radar["axis_count"] == 0:
                st.info("N각형 레이더를 표시하려면 전·후 결과가 있는 역량이 3개 이상 필요합니다.")

            st.caption(
                "그래프 아래의 역량별 값은 화면에서만 확인할 수 있습니다. "
                "파일 저장·인쇄용 리포트·CSV 다운로드 기능은 제공하지 않습니다."
            )
            st.stop()

    _render_csv_tools()
    st.stop()

if is_pre_post:
    profile_source = clean[clean["session_type"].eq("post")]
else:
    profile_source = clean
rows = aggregate_factor_results(profile_source.to_dict("records"))
if not rows:
    st.error("집계할 수 있는 유효 결과가 없습니다.")
    _render_csv_tools()
    st.stop()

source_codes = set(clean["factor_code"])
project_was_configured = bool(st.session_state.get("selected_factors"))
radar_factor_order = sorted(str(code) for code in source_codes)
if source_kind == "session":
    radar_factor_order = [
        str(code)
        for code in st.session_state.get("selected_factors", [])
        if str(code) in source_codes
    ]
    configured_targets = {
        str(code): float(value)
        for code, value in st.session_state.get("target_means", {}).items()
        if code in source_codes
    }
    organization_priorities = set(st.session_state.get("organization_priorities", []))
    project_name = str(st.session_state.get("project_name", "조직 교육평가"))
    report_period = f"{st.session_state.get('pre_end_date')} ~ {st.session_state.get('post_end_date')}"
elif source_kind == "store":
    radar_factor_order = [
        str(code)
        for code in stored_project.get("selected_factors", [])
        if str(code) in source_codes
    ]
    configured_targets = {
        code: value
        for code, value in stored_target_means.items()
        if code in source_codes
    }
    raw_store_priorities = stored_project.get("organization_priorities")
    organization_priorities = (
        {
            str(code).strip()
            for code in raw_store_priorities
            if str(code).strip() in source_codes
        }
        if isinstance(raw_store_priorities, (list, tuple, set))
        else set()
    )
    project_name = str(
        stored_project.get("project_name") or f"TAP 조직 교육평가 · {store_project_code}"
    )
    report_period = (
        f"{stored_project.get('pre_start_date') or '-'} ~ "
        f"{stored_project.get('post_end_date') or '-'}"
    )
elif is_sample:
    configured_targets = {}
    organization_priorities = set()
    project_name = "TAP 교육 전·후 변화 예시"
    report_period = "예시 교육 전·후 기간"
else:
    # 업로드 결과는 현재 브라우저 세션의 다른 프로젝트 설정과 절대 섞지 않는다.
    configured_targets = {}
    organization_priorities = set()
    project_id = str(clean["project_id"].iloc[0])
    project_name = f"TAP 조직 교육평가 · {project_id}"
    assessment_dates = pd.to_datetime(clean["assessment_date"], errors="coerce").dt.date
    first_date, last_date = assessment_dates.min(), assessment_dates.max()
    report_period = str(first_date) if first_date == last_date else f"{first_date} ~ {last_date}"

participant_count = (
    int(pre_post_summary["post_participant_count"])
    if pre_post_summary
    else int(clean["participant_id"].nunique())
)
model = build_organization_report_model(
    rows,
    participant_count=participant_count,
    project_name=project_name,
    report_period=report_period,
    target_means=configured_targets,
    organization_priorities=organization_priorities,
    is_sample=is_sample,
    demo_target=3.5 if is_sample and not configured_targets else None,
    pre_post_summary=pre_post_summary,
)

if is_pre_post and pre_post_summary:
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("교육 전 참여", f"{pre_post_summary['pre_participant_count']}명")
    k2.metric("교육 후 참여", f"{pre_post_summary['post_participant_count']}명")
    k3.metric("짝지어진 참여", f"{pre_post_summary['paired_participant_count']}명")
    attrition_rate = pre_post_summary.get("attrition_rate")
    k4.metric("사후 이탈률", "—" if attrition_rate is None else f"{attrition_rate:.1f}%")
    result = pd.DataFrame(pre_post_summary["comparison_rows"])
    result_download = result.rename(
        columns={
            "factor_name_ko": "역량",
            "pre_n": "교육 전 N",
            "post_n": "교육 후 N",
            "paired_n": "짝지어진 N",
            "pre_mean": "교육 전 평균",
            "post_mean": "교육 후 평균",
            "change": "관찰 변화",
            "status": "공개상태",
        }
    )
else:
    result = pd.DataFrame(rows)
    result_download = result.rename(
        columns={
            "factor_name_ko": "역량",
            "n": "유효 N",
            "group_mean": "조직 평균(1~5)",
            "status": "공개상태",
        }
    )

if is_pre_post and pre_post_summary:
    priority_codes = set(str(code) for code in organization_priorities)
    preferred_radar_codes = [
        code for code in radar_factor_order if code in priority_codes
    ] + [code for code in radar_factor_order if code not in priority_codes]
    st.markdown("### 교육 전후 비교 포인트")
    st.caption(
        "동일 참여자의 교육 전 평균은 파란색, 교육 후 평균은 청록색으로 표시합니다. "
        "공개 역량이 8개를 넘으면 그래프에 표시할 3~8개를 직접 선택합니다."
    )
    ordered_public_rows = _ordered_preview_rows(
        list(pre_post_summary["comparison_rows"]),
        preferred_radar_codes,
    )
    selected_public_rows = ordered_public_rows
    if len(ordered_public_rows) > 8:
        public_factor_labels = {
            str(row["factor_code"]): str(row["factor_name_ko"])
            for row in ordered_public_rows
        }
        radar_scope = selected_project_key or f"{source_kind}:{project_name}"
        selected_public_codes = st.multiselect(
            "레이더에 표시할 역량 · 3~8개",
            list(public_factor_labels),
            default=list(public_factor_labels)[:8],
            key=_project_widget_key(PUBLIC_RADAR_AXES_PREFIX, radar_scope),
            max_selections=8,
            format_func=lambda code: public_factor_labels[code],
        )
        selected_public_set = set(selected_public_codes)
        selected_public_rows = [
            row
            for row in ordered_public_rows
            if str(row["factor_code"]) in selected_public_set
        ]

    if len(selected_public_rows) >= 3:
        selected_public_codes = [
            str(row["factor_code"]) for row in selected_public_rows
        ]
        radar = build_pre_post_radar(
            selected_public_rows,
            title=f"교육 전·후 역량 변화 · {len(selected_public_rows)}개",
            min_paired_n=MIN_GROUP_N,
            preferred_codes=selected_public_codes,
            max_axes=min(8, len(selected_public_rows)),
        )
        st.html(radar["html"])
    else:
        st.warning("N각형 레이더를 표시하려면 공개 역량을 3개 이상 선택해 주세요.")

    omitted_public_count = len(ordered_public_rows) - len(selected_public_rows)
    if omitted_public_count:
        st.info(
            f"공개 가능한 역량 중 선택하지 않은 {omitted_public_count}개는 상세표에서 확인할 수 있습니다. "
            "레이더 그래프는 가독성을 위해 최대 8개를 표시합니다."
        )

html_report = printable_organization_report_html(model)
file_stem = "tap_organization_pre_post_report" if is_pre_post else "tap_organization_report"
download_html, download_csv = st.columns(2)
download_html.download_button(
    "인쇄용 리포트 HTML",
    html_report.encode("utf-8-sig"),
    f"{file_stem}.html",
    "text/html",
    width="stretch",
    help="내려받은 파일을 브라우저에서 열고 인쇄 → PDF 저장을 선택하세요.",
)
download_csv.download_button(
    "상세 결과 CSV",
    result_download.to_csv(index=False).encode("utf-8-sig"),
    f"{file_stem}_detail.csv",
    "text/csv",
    width="stretch",
)

st.html(organization_report_fragment(model))

with st.expander("집계 검수표 보기"):
    st.caption(
        "전후 비교는 동일 participant_id의 짝지어진 결과만 사용합니다. N≥5는 개인정보 보호를 위한 최소 공개 규칙이며 "
        "평균의 통계적 안정성이나 교육의 인과효과를 보장하지 않습니다."
    )
    st.dataframe(result_download, hide_index=True, width="stretch")

_render_csv_tools()
