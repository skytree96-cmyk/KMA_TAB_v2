from __future__ import annotations

import io

import pandas as pd
import streamlit as st

from tap.aggregation import aggregate_factor_results
from tap.config import DATA_DIR, MIN_GROUP_N
from tap.data import load_competencies
from tap.reporting import (
    build_organization_report_model,
    build_pre_post_group_summary,
    organization_report_fragment,
    prepare_group_results,
    printable_organization_report_html,
)
from tap.state import ensure_state
from tap.ui import callout, page_header, setup_page


setup_page("교육 전후 리포트", "4")
ensure_state(st.session_state)
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

template_csv = """participant_id,factor_code,score_1_to_5,project_id,assessment_version,target_level,assessment_date,session_type,valid_items,na_items,missing_items,opportunity_1_to_5,manager_support_1_to_5,resource_support_1_to_5
P001,CORE-CO,3.0,PROJECT-001,TAP-1.0,manager,2026-08-01,pre,4,0,0,,,
P001,CORE-CO,3.8,PROJECT-001,TAP-1.0,manager,2026-10-01,post,4,0,0,4,4,3
P002,CORE-CO,3.2,PROJECT-001,TAP-1.0,manager,2026-08-01,pre,3,1,0,,,
P002,CORE-CO,3.7,PROJECT-001,TAP-1.0,manager,2026-10-01,post,4,0,0,3,4,4
"""

with st.expander("데이터 준비와 업로드", expanded=True):
    st.caption(
        "사전·사후 비교에는 같은 사람에게 같은 participant_id를 사용하고 session_type을 pre/post로 구분하세요. "
        "단일시점 기존 CSV도 계속 사용할 수 있습니다. 공개 데모에는 실제 개인정보나 기밀자료를 업로드하지 마세요."
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
        uploaded = st.file_uploader(
            "익명 조직결과 CSV",
            type=["csv"],
            help=(
                "필수: participant_id, factor_code, score_1_to_5, project_id, "
                "assessment_version, target_level, assessment_date. 전후 비교 시 session_type도 필요합니다."
            ),
        )

is_sample = uploaded is None
if is_sample:
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
    source = pd.concat([pre_sample, post_sample], ignore_index=True)
    st.info("업로드 파일이 없어 교육 전·후 예시 데이터를 표시합니다. 모든 수치와 변화량은 실제 결과가 아닙니다.")
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

session_values = set(clean["session_type"].dropna()) if "session_type" in clean.columns else set()
is_pre_post = {"pre", "post"}.issubset(session_values)
pre_post_summary = build_pre_post_group_summary(clean, min_group_n=MIN_GROUP_N) if is_pre_post else None

if is_pre_post:
    profile_source = clean[clean["session_type"].eq("post")]
else:
    profile_source = clean
rows = aggregate_factor_results(profile_source.to_dict("records"))
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
        else "TAP 교육 전·후 변화 예시"
    )
    report_period = (
        f"{st.session_state.get('project_start_date')} ~ {st.session_state.get('project_end_date')}"
        if project_was_configured
        else "예시 교육 전·후 기간"
    )
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
