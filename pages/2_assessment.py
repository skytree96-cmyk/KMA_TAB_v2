from __future__ import annotations

import hashlib
from datetime import date
from html import escape
from time import time

import streamlit as st

from tap.baseline_transfer import BaselineValidationError, bootstrap_post_from_pre_baseline
from tap.config import LIKERT_OPTIONS
from tap.data import questions_for_factors
from tap.state import (
    PARTICIPANT_ID_WIDGET_KEY,
    ensure_state,
    load_participant_id_widget,
    reset_assessment,
    save_participant_id_widget,
    sync_assessment_phase,
)
from tap.ui import callout, page_header, setup_page


setup_page("검사 참여", "2")
ensure_state(st.session_state)


def _render_post_baseline_entry(*, key: str) -> None:
    """Restore a completed pre assessment before the post questionnaire starts."""
    with st.container(border=True):
        st.markdown("### 교육 후 검사 이어하기")
        st.markdown(
            "**1. 기준파일 선택 → 2. 교육 전 결과·참여자 ID 자동 복원 → "
            "3. 교육 후 검사 시작**"
        )
        st.caption(
            "교육 전 검사 완료 직후 개인 리포트에서 저장한 "
            "`tap_pre_baseline_…json` 파일을 선택하세요. "
            "일반 결과 JSON은 사용할 수 없습니다."
        )
        uploaded_baseline = st.file_uploader(
            "교육 전 검사 기준파일(JSON)",
            type=["json"],
            help=(
                "파일 안의 프로젝트·교육일·선택 역량·검사 버전·문항 스냅샷을 "
                "현재 문항은행과 확인한 뒤 교육 후 검사 상태를 자동으로 구성합니다."
            ),
            key=key,
        )
        if uploaded_baseline is None:
            return
        try:
            restored = bootstrap_post_from_pre_baseline(
                st.session_state,
                uploaded_baseline.getvalue(),
            )
        except BaselineValidationError as exc:
            st.error(f"기준파일을 불러오지 못했습니다: {exc}")
            return

        st.session_state["baseline_restore_notice"] = (
            f"교육 전 검사 {len(restored['responses'])}개 문항과 교육 참여자 ID를 "
            "복원했습니다. 이제 교육 후 검사에 응답해 주세요."
        )
        st.rerun()


if not st.session_state.selected_factors:
    page_header(
        "검사 참여",
        "교육 전·후 검사 시작",
        "교육 전 검사는 설정된 프로젝트로 시작하고, 교육 후 검사는 저장해 둔 기준파일로 바로 이어갑니다.",
        badge="참여자",
    )
    _render_post_baseline_entry(key="pre_baseline_bootstrap_uploader")
    st.markdown("#### 교육 전 검사를 시작하시나요?")
    st.caption("교육담당자가 먼저 교육과정·일정·측정역량을 설정해야 합니다.")
    if st.button("교육평가 프로젝트 설정으로 이동", type="primary"):
        st.switch_page("pages/1_project_setup.py")
    st.stop()

phase = str(st.session_state.get("assessment_phase", "pre"))
if phase not in {"pre", "post"}:
    phase = "pre"
    st.session_state.assessment_phase = phase

phase_labels = {"pre": "교육 전 역량평가", "post": "교육 후 역량평가"}
phase_short_labels = {"pre": "교육 전", "post": "교육 후"}
period_start = st.session_state.get(f"{phase}_start_date", "미설정")
period_end = st.session_state.get(f"{phase}_end_date", "미설정")

questions = questions_for_factors(st.session_state.selected_factors)
if not questions:
    st.error("현재 프로젝트에서 응답할 문항을 찾지 못했습니다.")
    st.stop()

# 사전·사후의 문항과 제시 순서를 동일하게 고정해 문항 차이가 변화점수에 섞이지 않게 한다.
order_seed = str(st.session_state.get("project_name", "TAP"))
stored_order = [str(code) for code in st.session_state.get("question_snapshot_codes", [])]
question_by_code = {str(row["question_code"]): row for row in questions}
if stored_order and set(stored_order) == set(question_by_code):
    questions = [question_by_code[code] for code in stored_order]
else:
    questions = sorted(
        questions,
        key=lambda row: hashlib.sha256(f"{order_seed}|{row['question_code']}".encode("utf-8")).hexdigest(),
    )

snapshot_rows = sorted(
    (
        str(row["question_code"]),
        str(row["revised_text"]),
        str(row.get("scoring_direction", "direct")),
    )
    for row in questions
)
snapshot_hash = hashlib.sha256(
    "\n".join("|".join(parts) for parts in snapshot_rows).encode("utf-8")
).hexdigest()
stored_snapshot = str(st.session_state.get("question_snapshot_hash", ""))
if stored_snapshot and stored_snapshot != snapshot_hash:
    st.error("프로젝트 저장 후 문항 버전이 변경되어 비교를 중단했습니다. 교육담당자가 새 프로젝트로 다시 설정해 주세요.")
    st.stop()
if not stored_snapshot:
    st.session_state.question_snapshot_hash = snapshot_hash
    st.session_state.question_snapshot_codes = [str(row["question_code"]) for row in questions]
    st.session_state.assessment_version = f"TAP-1.0+{snapshot_hash[:12]}"

responses: dict[str, int] = st.session_state.responses
question_codes = {str(row["question_code"]) for row in questions}
answered = sum(code in responses for code in question_codes)
idx = min(max(int(st.session_state.current_question), 0), len(questions) - 1)
question = questions[idx]
completed_by_phase = st.session_state.get("assessment_completed_by_phase", {})
pre_complete = bool(completed_by_phase.get("pre", False))
post_complete = bool(completed_by_phase.get("post", False))

if phase == "post" and not pre_complete:
    page_header(
        "검사 참여",
        f"교육 후 검사 이어하기 · {st.session_state.get('course_name', '교육과정')}",
        "교육 전 검사 기준파일을 먼저 복원해야 동일 참여자·동일 문항의 변화를 비교할 수 있습니다.",
        badge="교육 후",
    )
    callout(
        "교육 전 검사 기준파일 필요",
        "교육 전 검사 완료 직후 저장한 기준파일을 선택하면 프로젝트와 참여자 ID가 자동으로 복원됩니다.",
        icon="!",
        tone="warn",
    )
    _render_post_baseline_entry(key="pre_baseline_post_uploader")
    st.caption(
        "기준파일을 분실한 경우 현재 공개 데모에서는 교육 전·후 비교를 복원할 수 없습니다. "
        "교육담당자에게 문의해 주세요."
    )
    st.stop()

try:
    window_start = date.fromisoformat(str(period_start))
    window_end = date.fromisoformat(str(period_end))
except ValueError:
    window_start = window_end = None
today = date.today()
outside_window = bool(window_start and window_end and not (window_start <= today <= window_end))
if outside_window and not st.session_state.get("allow_schedule_override", True):
    st.warning(f"{phase_labels[phase]} 기간({period_start} ~ {period_end})이 아닙니다. 교육담당자에게 문의해 주세요.")
    st.stop()
if outside_window:
    st.caption("공개 데모 미리보기 모드 · 실제 운영에서는 설정된 검사기간 안에서만 제출할 수 있습니다.")

if st.session_state.assessment_started_at is None:
    st.session_state.assessment_started_at = time()
    sync_assessment_phase(st.session_state)

page_header(
    "검사 참여",
    f"{phase_labels[phase]} · {st.session_state.get('course_name', '교육과정')}",
    "사전·사후 모두 동일하게 최근 8주 동안 실제 업무에서 나타난 행동을 기준으로 응답해 주세요.",
    badge=phase_short_labels[phase],
)

restore_notice = st.session_state.pop("baseline_restore_notice", "")
if restore_notice:
    st.success(restore_notice)
    for warning in st.session_state.get("baseline_restore_warnings", []):
        st.warning(warning)

status_parts = [
    f"교육 전 {'완료' if pre_complete else '미완료'}",
    f"교육 후 {'완료' if post_complete else '미완료'}",
]
st.caption(
    f"검사 기간 {period_start} ~ {period_end} · 교육일 {st.session_state.get('training_date', '미설정')} "
    f"· {' · '.join(status_parts)}"
)

callout(
    "교육개발 목적의 자기보고형 변화검사",
    "양 시점의 동일 참여자·동일 문항 결과를 연결해 '교육 전후 관찰된 변화'를 봅니다. 채용·승진·보상·성과평가의 단독 판단자료로 사용하지 않습니다.",
    icon="i",
)

participant_id_missing = not str(st.session_state.get("participant_id", "")).strip()
load_participant_id_widget(st.session_state)
st.text_input(
    "교육 참여자 ID",
    key=PARTICIPANT_ID_WIDGET_KEY,
    on_change=save_participant_id_widget,
    args=(st.session_state,),
    disabled=pre_complete and not participant_id_missing,
    help="교육 전·후에 같은 ID를 사용해야 변화가 연결됩니다. 이름·사번 같은 직접 식별정보는 입력하지 마세요.",
)
if pre_complete and not participant_id_missing:
    st.caption("교육 전 검사에 사용한 ID로 자동 연결되어 변경할 수 없습니다.")
participant_id_missing = not str(st.session_state.get("participant_id", "")).strip()
if participant_id_missing:
    st.warning(
        "교육 전·후 결과를 연결할 교육 참여자 ID를 입력해 주세요. "
        "문항은 미리 볼 수 있지만 ID 입력 전에는 응답을 저장할 수 없습니다."
    )

def _finish_phase() -> None:
    """Complete and persist the active phase before opening its report."""
    st.session_state.assessment_completed = True
    st.session_state.assessment_completed_at_by_phase[phase] = date.today().isoformat()
    started = st.session_state.assessment_started_at or time()
    st.session_state.duration_seconds = max(0, time() - started)
    sync_assessment_phase(st.session_state)
    st.switch_page("pages/3_individual_report.py")


def _render_transfer_environment() -> None:
    """Collect post-only context; these fields never enter competency scores."""
    stored = dict(st.session_state.get("post_transfer_responses", {}))
    st.progress(1.0, text=f"{len(questions)}/{len(questions)} 역량문항 응답 완료")
    st.markdown("### 현업전이 환경 확인")
    st.caption(
        "교육 내용을 실제 업무에 쓸 수 있었는지를 확인합니다. "
        "아래 응답은 역량점수에 합산하지 않고, 변화의 맥락과 후속조치를 정하는 데만 사용합니다."
    )
    transfer_options = [1, 2, 3, 4, 5]
    transfer_labels = {
        1: "전혀 그렇지 않다",
        2: "그렇지 않은 편이다",
        3: "보통이다",
        4: "그런 편이다",
        5: "매우 그렇다",
    }
    items = [
        ("application_opportunity", "교육에서 배운 내용을 업무에 적용할 기회가 있었다."),
        ("supervisor_support", "상사·리더가 배운 내용을 적용하도록 지원했다."),
        ("resources_authority", "적용에 필요한 도구·정보·권한이 충분했다."),
        ("time_process_support", "업무시간과 프로세스가 새로운 방식을 적용하기에 적합했다."),
    ]
    with st.form("post_transfer_environment_form"):
        values: dict[str, int] = {}
        for key, label in items:
            saved_value = stored.get(key)
            values[key] = st.radio(
                label,
                options=transfer_options,
                index=transfer_options.index(saved_value) if saved_value in transfer_options else None,
                format_func=lambda value: f"{value}. {transfer_labels[value]}",
                horizontal=True,
                key=f"transfer_{key}",
            )
        barriers = st.multiselect(
            "적용을 방해한 요인(복수 선택)",
            options=["적용 기회 부족", "상사·동료 지원 부족", "도구·정보·권한 부족", "시간·프로세스 제약", "특별한 방해요인 없음"],
            default=stored.get("barriers", []),
        )
        applied_content = st.text_area(
            "실제 업무에 적용한 교육 내용(선택)",
            value=str(stored.get("applied_content", "")),
            placeholder="예: 1:1 면담에서 질문·피드백 구조를 적용함",
        )
        submitted = st.form_submit_button("교육 후 검사 완료", type="primary", width="stretch")

    if submitted:
        if not str(st.session_state.get("participant_id", "")).strip():
            st.error("교육 참여자 ID를 입력한 뒤 교육 후 검사 완료를 다시 눌러 주세요.")
            return
        if any(value is None for value in values.values()):
            st.error("현업전이 항목 4개에 모두 응답해 주세요.")
            return
        st.session_state.post_transfer_responses = {
            **values,
            "barriers": barriers,
            "applied_content": applied_content.strip(),
        }
        _finish_phase()


if answered == len(questions) and phase == "post" and not st.session_state.assessment_completed:
    _render_transfer_environment()
    st.stop()

if st.session_state.assessment_completed:
    st.success(f"{phase_labels[phase]}가 완료되었습니다.")
    if st.button("결과 다시 보기", type="primary", width="stretch"):
        st.switch_page("pages/3_individual_report.py")
    st.stop()

options = list(LIKERT_OPTIONS)
current_value = responses.get(question["question_code"])
with st.container(border=True):
    st.markdown('<span class="tap-question-stage-anchor" aria-hidden="true"></span>', unsafe_allow_html=True)
    st.markdown(
        f"""
        <div class="tap-assessment-progress-head">
          <div class="tap-assessment-progress-count"><b>{idx + 1}</b><span>/ {len(questions)}</span></div>
          <div class="tap-assessment-progress-status">{answered}개 응답 완료</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.progress((idx + 1) / len(questions))
    st.markdown(
        f"""
        <section class="tap-question-panel">
          <div class="tap-question-meta">
            <span class="tap-factor-pill">{escape(str(question['factor_name_ko']))}</span>
            <span class="tap-period-pill">최근 8주</span>
          </div>
          <p class="tap-question-number">{phase_short_labels[phase]} 업무행동 · 문항 {idx + 1}</p>
          <h2>{escape(question['revised_text'])}</h2>
        </section>
        """,
        unsafe_allow_html=True,
    )

    with st.form(f"question_form_{phase}_{question['question_code']}"):
        st.markdown(
            """
            <div class="tap-response-head tap-response-anchor">
              <b>얼마나 자주 했습니까?</b>
              <span>해당 행동을 할 상황이 없었다면 0을 선택하세요.</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        choice = st.radio(
            "응답",
            options=options,
            index=options.index(current_value) if current_value in options else None,
            format_func=lambda value: LIKERT_OPTIONS[value],
            horizontal=True,
            label_visibility="collapsed",
        )
        if idx == len(questions) - 1:
            submit_label = "저장하고 현업전이 문항" if phase == "post" else "교육 전 결과 보기"
        else:
            submit_label = "다음 문항 →"
        submitted = st.form_submit_button(submit_label, type="primary", width="stretch")

    if submitted:
        if not str(st.session_state.get("participant_id", "")).strip():
            st.error("교육 참여자 ID를 입력한 뒤 다음 문항을 다시 눌러 주세요. 선택한 응답은 그대로 유지됩니다.")
        elif choice is None:
            st.error("응답을 선택해 주세요. 수행 기회가 없었다면 '수행 기회 없음'을 선택하세요.")
        else:
            responses[question["question_code"]] = int(choice)
            st.session_state.responses = responses
            if idx == len(questions) - 1:
                sync_assessment_phase(st.session_state)
                if phase == "post":
                    st.rerun()
                else:
                    _finish_phase()
            else:
                st.session_state.current_question = idx + 1
                sync_assessment_phase(st.session_state)
                st.rerun()

    left, right = st.columns(2)
    with left:
        if st.button("← 이전 문항", disabled=idx == 0, width="stretch"):
            st.session_state.current_question = idx - 1
            sync_assessment_phase(st.session_state)
            st.rerun()
    with right:
        with st.popover(f"{phase_short_labels[phase]} 검사 초기화", width="stretch"):
            st.write(f"현재 {phase_short_labels[phase]} 응답만 모두 지웁니다. 다른 시점의 응답은 유지됩니다.")
            if st.button("초기화 확인", type="secondary"):
                reset_assessment(st.session_state, phase)
                st.rerun()
