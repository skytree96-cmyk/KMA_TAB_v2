from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from tap.aggregation import aggregate_factor_results
from tap.config import DATA_DIR, MIN_GROUP_N
from tap.data import load_competencies
from tap.reporting import (
    build_organization_report_model,
    organization_report_fragment,
    prepare_group_results,
    printable_organization_report_html,
)
from tap.state import ensure_state
from tap.ui import callout, page_header, setup_page


setup_page("조직 리포트", "4")
ensure_state(st.session_state)
page_header(
    "조직 리포트",
    "조직 교육수요 리포트",
    "익명 집계의 의미와 제한을 함께 보여주는 페이퍼형 리포트입니다.",
    badge=f"유효 N≥{MIN_GROUP_N}만 공개",
)
callout(
    "개인 순위는 제공하지 않습니다",
    "조직의 공통 개발영역을 탐색하며, 채용·승진·보상·성과평가의 판단자료로 사용할 수 없습니다.",
    icon="5+",
)

template_csv = """participant_id,factor_code,score_1_to_5,project_id,assessment_version,target_level,assessment_date
P001,CORE-CO,3.5,PROJECT-001,TAP-0.9,manager,2026-08-12
P002,CORE-CO,4.0,PROJECT-001,TAP-0.9,manager,2026-08-12
"""

with st.expander("데이터 준비와 업로드", expanded=True):
    st.caption(
        "개인 결과를 직접 올리지 말고, 참여자별 역량 평균만 익명 ID로 준비하세요. "
        "공개 데모에는 실제 개인정보나 기밀자료를 업로드하지 마세요."
    )
    download_col, upload_col = st.columns([1, 2])
    with download_col:
        st.download_button(
            "CSV 양식 내려받기",
            template_csv.encode("utf-8-sig"),
            "tap_group_result_template.csv",
            "text/csv",
            width="stretch",
        )
    with upload_col:
        uploaded = st.file_uploader(
            "익명 조직결과 CSV",
            type=["csv"],
            help=(
                "필수: participant_id, factor_code, score_1_to_5, project_id, "
                "assessment_version, target_level, assessment_date"
            ),
        )

is_sample = uploaded is None
if is_sample:
    source = pd.read_csv(DATA_DIR / "sample_group_results.csv")
    st.info("업로드 파일이 없어 예시 데이터를 표시합니다. 모든 수치와 목표는 실제 회원사 결과가 아닙니다.")
else:
    raw = uploaded.getvalue()
    try:
        source = pd.read_csv(io.BytesIO(raw), encoding="utf-8-sig")
    except UnicodeDecodeError:
        try:
            source = pd.read_csv(io.BytesIO(raw), encoding="cp949")
        except (UnicodeDecodeError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            st.error(f"CSV 인코딩 또는 구조를 읽을 수 없습니다: {exc}")
            st.stop()
    except (pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        st.error(f"CSV 구조를 읽을 수 없습니다: {exc}")
        st.stop()

clean, validation_errors, validation_warnings = prepare_group_results(
    source,
    load_competencies(),
    require_metadata=not is_sample,
)
for warning in validation_warnings:
    st.warning(warning)
if validation_errors:
    for error in validation_errors:
        st.error(error)
    st.stop()

rows = aggregate_factor_results(clean.to_dict("records"))
if not rows:
    st.error("집계할 수 있는 유효 결과가 없습니다.")
    st.stop()

source_codes = set(clean["factor_code"])
project_was_configured = bool(st.session_state.get("selected_factors"))
if is_sample:
    configured_targets = {
        str(code): float(value)
        for code, value in st.session_state.get("target_means", {}).items()
        if code in source_codes
    }
    organization_priorities = set(st.session_state.get("organization_priorities", []))
    project_name = (
        str(st.session_state.get("project_name", "조직 진단"))
        if project_was_configured
        else "TAP 조직 진단 예시"
    )
    report_period = (
        f"{st.session_state.get('project_start_date')} ~ {st.session_state.get('project_end_date')}"
        if project_was_configured
        else "예시 집계 기간"
    )
else:
    # 업로드 결과는 현재 브라우저 세션의 다른 프로젝트 설정과 절대 섞지 않는다.
    configured_targets = {}
    organization_priorities = set()
    project_id = str(clean["project_id"].iloc[0])
    project_name = f"TAP 조직 진단 · {project_id}"
    assessment_dates = pd.to_datetime(clean["assessment_date"], errors="coerce").dt.date
    first_date, last_date = assessment_dates.min(), assessment_dates.max()
    report_period = str(first_date) if first_date == last_date else f"{first_date} ~ {last_date}"
model = build_organization_report_model(
    rows,
    participant_count=int(clean["participant_id"].nunique()),
    project_name=project_name,
    report_period=report_period,
    target_means=configured_targets,
    organization_priorities=organization_priorities,
    is_sample=is_sample,
    demo_target=3.5 if is_sample and not configured_targets else None,
)

result = pd.DataFrame(rows)
result_download = result.rename(
    columns={
        "factor_name_ko": "역량",
        "n": "유효 N",
        "group_mean": "조직 평균(1~5)",
        "status": "공개상태",
    }
)
html_report = printable_organization_report_html(model)
download_html, download_csv = st.columns(2)
download_html.download_button(
    "인쇄용 리포트 HTML",
    html_report.encode("utf-8-sig"),
    "tap_organization_report.html",
    "text/html",
    width="stretch",
    help="내려받은 파일을 브라우저에서 열고 인쇄 → PDF 저장을 선택하세요.",
)
download_csv.download_button(
    "상세 결과 CSV",
    result_download.to_csv(index=False).encode("utf-8-sig"),
    "tap_organization_report_detail.csv",
    "text/csv",
    width="stretch",
)

st.html(organization_report_fragment(model))

with st.expander("집계 검수표 보기"):
    st.caption(
        "N≥5는 개인정보 보호를 위한 최소 공개 규칙이며 평균의 통계적 안정성을 보장하지 않습니다. "
        "운영 전에는 버전·대상수준·프로젝트가 섞이지 않았는지도 확인해야 합니다."
    )
    st.dataframe(result_download, hide_index=True, width="stretch")
