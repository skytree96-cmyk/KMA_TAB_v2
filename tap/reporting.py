from __future__ import annotations

import math
from datetime import date
from html import escape
from textwrap import dedent
from typing import Any, Iterable, Mapping

import pandas as pd


GROUP_REQUIRED_COLUMNS = ("participant_id", "factor_code", "score_1_to_5")
GROUP_METADATA_COLUMNS = ("project_id", "assessment_version", "target_level", "assessment_date")


def prepare_group_results(
    frame: pd.DataFrame,
    competency_rows: Iterable[Mapping[str, Any]],
    *,
    require_metadata: bool = False,
) -> tuple[pd.DataFrame, list[str], list[str]]:
    """Validate uploaded factor-level results and apply canonical Korean names."""
    errors: list[str] = []
    warnings: list[str] = []
    missing = [column for column in GROUP_REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        return frame.copy(), ["필수 열이 없습니다: " + ", ".join(missing)], warnings
    if frame.empty:
        return frame.copy(), ["업로드 파일에 결과 행이 없습니다."], warnings

    work = frame.copy()
    work["participant_id"] = work["participant_id"].astype("string").fillna("").str.strip()
    work["factor_code"] = work["factor_code"].astype("string").fillna("").str.strip()
    blank_ids = work.index[work["participant_id"].eq("")].tolist()
    blank_codes = work.index[work["factor_code"].eq("")].tolist()
    if blank_ids:
        errors.append(f"참여자 식별자가 빈 행이 {len(blank_ids)}개 있습니다.")
    if blank_codes:
        errors.append(f"역량코드가 빈 행이 {len(blank_codes)}개 있습니다.")

    scores = pd.to_numeric(work["score_1_to_5"], errors="coerce")
    invalid_number = scores.isna() | ~scores.map(lambda value: math.isfinite(float(value)) if pd.notna(value) else False)
    if invalid_number.any():
        errors.append(f"점수가 숫자가 아니거나 유한하지 않은 행이 {int(invalid_number.sum())}개 있습니다.")
    outside = scores.notna() & ((scores < 1) | (scores > 5))
    if outside.any():
        errors.append(f"점수가 1~5 범위를 벗어난 행이 {int(outside.sum())}개 있습니다.")
    work["score_1_to_5"] = scores

    canonical = {
        str(row["factor_code"]): str(row["factor_name_ko"])
        for row in competency_rows
        if bool(row.get("active_for_scoring", True))
    }
    unknown = sorted(set(work["factor_code"].dropna()) - set(canonical))
    if unknown:
        errors.append("등록되지 않은 역량코드가 있습니다: " + ", ".join(unknown))

    if "factor_name_ko" in work.columns:
        supplied = work["factor_name_ko"].astype("string").fillna("").str.strip()
        mismatch_count = sum(
            bool(code in canonical and supplied_name and supplied_name != canonical[code])
            for code, supplied_name in zip(work["factor_code"], supplied, strict=False)
        )
        if mismatch_count:
            warnings.append(
                f"역량코드와 한글명이 다른 행 {mismatch_count}개는 공식 한글명으로 교체했습니다."
            )
    work["factor_name_ko"] = work["factor_code"].map(canonical).fillna("")

    duplicate_count = int(work.duplicated(["participant_id", "factor_code"], keep=False).sum())
    if duplicate_count:
        warnings.append(
            f"같은 참여자·역량의 중복 행이 {duplicate_count}개 있습니다. 참여자별 평균으로 먼저 축약합니다."
        )

    if require_metadata:
        missing_metadata = [column for column in GROUP_METADATA_COLUMNS if column not in work.columns]
        if missing_metadata:
            errors.append(
                "프로젝트·버전 혼합 방지를 위해 다음 메타데이터 열이 필요합니다: "
                + ", ".join(missing_metadata)
            )
        for column in GROUP_METADATA_COLUMNS:
            if column not in work.columns:
                continue
            values = work[column].astype("string").fillna("").str.strip()
            blank_count = int(values.eq("").sum())
            if blank_count:
                errors.append(f"{column} 값이 빈 행이 {blank_count}개 있습니다.")
            unique = sorted(value for value in values.unique().tolist() if value)
            if column != "assessment_date" and len(unique) > 1:
                errors.append(f"{column} 값이 둘 이상 섞여 있습니다: {', '.join(unique[:5])}")
            if column == "assessment_date":
                parsed_dates = pd.to_datetime(values.where(values.ne("")), errors="coerce")
                invalid_dates = int((values.ne("") & parsed_dates.isna()).sum())
                if invalid_dates:
                    errors.append(f"assessment_date 형식이 올바르지 않은 행이 {invalid_dates}개 있습니다.")
            if column == "target_level":
                invalid_levels = sorted(set(unique) - {"staff", "manager", "executive"})
                if invalid_levels:
                    errors.append("target_level 값은 staff, manager, executive 중 하나여야 합니다.")

    ordered = list(GROUP_REQUIRED_COLUMNS) + ["factor_name_ko"]
    ordered += [column for column in GROUP_METADATA_COLUMNS if column in work.columns]
    return work[ordered], errors, warnings


def build_organization_report_model(
    aggregate_rows: Iterable[Mapping[str, Any]],
    *,
    participant_count: int,
    project_name: str,
    report_period: str,
    target_means: Mapping[str, float] | None = None,
    organization_priorities: set[str] | None = None,
    is_sample: bool = False,
    demo_target: float | None = None,
) -> dict[str, Any]:
    targets = {str(code): float(value) for code, value in (target_means or {}).items()}
    selected_priorities = organization_priorities or set()
    factors: list[dict[str, Any]] = []
    suppressed = 0
    for source in aggregate_rows:
        code = str(source["factor_code"])
        score = source.get("group_mean")
        if score is None:
            suppressed += 1
            continue
        target = targets.get(code)
        target_source = "프로젝트 설정"
        if target is None and is_sample and demo_target is not None:
            target = float(demo_target)
            target_source = "데모 임시값"
        gap = round(max(0.0, target - float(score)), 2) if target is not None else None
        factors.append(
            {
                "factor_code": code,
                "factor_name_ko": str(source["factor_name_ko"]),
                "n": int(source["n"]),
                "score": float(score),
                "target": target,
                "target_source": target_source if target is not None else None,
                "gap": gap,
                "organization_priority": code in selected_priorities,
            }
        )

    factors.sort(key=lambda row: (-row["score"], row["factor_name_ko"]))
    strength = factors[0] if factors else None
    development = factors[-1] if factors else None
    has_targets = any(row["target"] is not None for row in factors)
    if has_targets:
        priority_candidates = [row for row in factors if (row["gap"] or 0) > 0]
        priority_candidates.sort(
            key=lambda row: (
                not row["organization_priority"],
                -float(row["gap"] or 0),
                row["factor_name_ko"],
            )
        )
    else:
        priority_candidates = sorted(factors, key=lambda row: (row["score"], row["factor_name_ko"]))

    return {
        "project_name": project_name,
        "report_period": report_period,
        "generated_on": date.today().isoformat(),
        "participant_count": int(participant_count),
        "published_factor_count": len(factors),
        "suppressed_factor_count": suppressed,
        "factors": factors,
        "strength": strength,
        "development": development,
        "priorities": priority_candidates[:3],
        "has_targets": has_targets,
        "is_sample": bool(is_sample),
        "demo_target_used": bool(is_sample and any(row["target_source"] == "데모 임시값" for row in factors)),
    }


def _score_text(value: float | None) -> str:
    return "—" if value is None else f"{value:.2f}"


def _report_body(model: Mapping[str, Any]) -> str:
    factors = list(model["factors"])
    strength = model.get("strength")
    development = model.get("development")
    sample_badge = '<span class="tap-report-watermark">예시 데이터</span>' if model.get("is_sample") else ""
    target_note = (
        "데모 화면의 목표 3.50은 임시값이며 실제 의사결정에 사용할 수 없습니다."
        if model.get("demo_target_used")
        else "목표수준은 직무분석과 전문가 합의를 거쳐 역량·대상별로 설정해야 합니다."
    )

    bars = []
    for row in factors:
        width = max(0.0, min(100.0, (float(row["score"]) - 1) / 4 * 100))
        target_label = f" · 목표 {_score_text(row['target'])}" if row["target"] is not None else ""
        bars.append(
            f"""
            <div class="tap-report-score-row">
              <div><b>{escape(row['factor_name_ko'])}</b><small>유효 N={row['n']}{target_label}</small></div>
              <div class="tap-report-bar"><i style="width:{width:.1f}%"></i></div>
              <strong>{row['score']:.2f}</strong>
            </div>
            """
        )

    priority_rows = []
    for index, row in enumerate(model["priorities"], start=1):
        if model["has_targets"]:
            detail = (
                f"현재 {row['score']:.2f} · 목표 {_score_text(row['target'])} · "
                f"격차 {_score_text(row['gap'])}"
            )
            label = "교육 검토 우선순위"
        else:
            detail = f"조직 평균 {row['score']:.2f} · 목표수준 미설정"
            label = "개발 탐색 후보"
        priority_rows.append(
            f"""
            <div class="tap-report-priority">
              <span>{index}</span>
              <div><b>{escape(row['factor_name_ko'])}</b><small>{escape(detail)}</small></div>
              <em>{label}</em>
            </div>
            """
        )

    detail_rows = []
    for row in sorted(factors, key=lambda item: item["factor_name_ko"]):
        status = "목표 있음" if row["target"] is not None else "목표 미설정"
        detail_rows.append(
            "<tr>"
            f"<td>{escape(row['factor_name_ko'])}</td>"
            f"<td>{row['n']}</td>"
            f"<td>{row['score']:.2f}</td>"
            f"<td>{_score_text(row['target'])}</td>"
            f"<td>{_score_text(row['gap'])}</td>"
            f"<td>{status}</td>"
            "</tr>"
        )

    if strength and development:
        summary = (
            f"상대적으로 높은 응답 영역 후보는 <b>{escape(strength['factor_name_ko'])}</b> "
            f"({strength['score']:.2f}), 개발 맥락을 먼저 탐색할 영역은 "
            f"<b>{escape(development['factor_name_ko'])}</b> ({development['score']:.2f})입니다. "
            "작은 차이는 측정오차일 수 있으므로 순위로 해석하지 않습니다."
        )
    else:
        summary = "공개할 수 있는 역량 결과가 없습니다. 표본수와 데이터 품질을 먼저 확인하세요."

    return dedent(f"""
    <section class="tap-report-sheet tap-report-cover">
      {sample_badge}
      <header class="tap-report-brand"><span>TAP</span><div><b>KMA TAP</b><small>교육수요·업무행동 점검</small></div></header>
      <div class="tap-report-kicker">조직 리포트 · 탐색용</div>
      <h1>조직 교육수요 리포트</h1>
      <p class="tap-report-lead">개인의 순위를 매기지 않고, 조직의 공통 개발영역과 교육 검토 순서를 확인합니다.</p>
      <div class="tap-report-meta"><b>{escape(str(model['project_name']))}</b><span>{escape(str(model['report_period']))}</span><span>생성일 {model['generated_on']}</span></div>
      <div class="tap-report-kpis">
        <div><b>{model['participant_count']}명</b><span>익명 참여자</span></div>
        <div><b>{model['published_factor_count']}개</b><span>공개 역량</span></div>
        <div><b>{model['suppressed_factor_count']}개</b><span>소표본 보호</span></div>
        <div><b>1~5점</b><span>행동빈도 평균</span></div>
      </div>
      <div class="tap-report-summary">{summary}</div>
      <footer>최근 8주 자기보고 · 유효 N≥5만 공개 · 규준/백분위/개인순위 미제공</footer>
    </section>

    <section class="tap-report-sheet">
      {sample_badge}
      <div class="tap-report-kicker">01 · 조직 역량 프로필</div>
      <h2>조직 평균은 ‘얼마나 자주 했는가’를 보여줍니다</h2>
      <p class="tap-report-desc">1점은 전혀 없었다, 5점은 거의 항상 있었다입니다. 역량 간 작은 차이를 서열로 확정하지 마세요.</p>
      <div class="tap-report-score-list">{''.join(bars) or '<p>공개 결과 없음</p>'}</div>
      <div class="tap-report-method"><b>해석 원칙</b><span>평균과 N을 함께 보고, 수행기회·권한·도구·프로세스 맥락을 확인합니다.</span></div>
      <footer>조직 평균은 개인점수의 단순 순위표가 아닙니다.</footer>
    </section>

    <section class="tap-report-sheet">
      {sample_badge}
      <div class="tap-report-kicker">02 · 다음 행동</div>
      <h2>{'교육 검토 우선순위' if model['has_targets'] else '개발 탐색 후보'}</h2>
      <p class="tap-report-desc">낮은 평균만으로 교육을 확정하지 않습니다. 목표, 조직 중요도, 학습희망, 교육으로 해결 가능한 원인을 함께 확인합니다.</p>
      <div class="tap-report-priority-list">{''.join(priority_rows) or '<p>우선 검토 후보 없음</p>'}</div>
      <div class="tap-report-warning"><b>교육 전 확인</b><span>권한·도구·인력·시간·프로세스가 주원인이면 교육보다 조직개선을 먼저 실행합니다.</span></div>
      <div class="tap-report-method"><b>목표수준 주의</b><span>{escape(target_note)}</span></div>
      <footer>추천점수는 검토 순서를 돕는 휴리스틱이며 교육효과를 보장하지 않습니다.</footer>
    </section>

    <section class="tap-report-sheet">
      {sample_badge}
      <div class="tap-report-kicker">03 · 상세 및 방법</div>
      <h2>공개 가능한 결과만 상세표에 포함했습니다</h2>
      <table class="tap-report-table"><thead><tr><th>역량</th><th>유효 N</th><th>평균</th><th>목표</th><th>격차</th><th>상태</th></tr></thead><tbody>{''.join(detail_rows)}</tbody></table>
      <div class="tap-report-method-grid">
        <div><b>도구 상태</b><span>전문가 예비검토·인지면접 전 탐색용</span></div>
        <div><b>집계 보호</b><span>N&lt;5 비공개. 개인정보 기준과 통계적 안정성 기준은 별도 검토</span></div>
        <div><b>허용 목적</b><span>교육수요 탐색과 개발 대화</span></div>
        <div><b>금지 목적</b><span>채용·승진·보상·성과평가의 단독 판단</span></div>
      </div>
      <footer>KMA TAP · 진단 버전과 검증 상태를 확인한 뒤 사용하세요.</footer>
    </section>
    """).strip()


def organization_report_fragment(model: Mapping[str, Any]) -> str:
    # Streamlit/Markdown은 여러 raw-HTML 블록 사이의 들여쓰기·공백을 코드블록으로
    # 재해석할 수 있다. 화면 삽입본만 한 줄로 압축하고, 인쇄 HTML은 원형을 유지한다.
    compact_body = "".join(line.strip() for line in _report_body(model).splitlines())
    return f'<div class="tap-report-document">{compact_body}</div>'


def printable_organization_report_html(model: Mapping[str, Any]) -> str:
    css = """
    @page { size:A4; margin:0; }
    * { box-sizing:border-box; }
    body { margin:0; background:#e9efee; color:#102a2d; font-family:Pretendard,"Noto Sans KR","Malgun Gothic",sans-serif; }
    .tap-report-document { padding:18px 0; }
    .tap-report-sheet { position:relative; width:210mm; min-height:297mm; margin:0 auto 14px; padding:17mm 16mm 16mm; background:#fff; page-break-after:always; overflow:hidden; }
    .tap-report-sheet:last-child { page-break-after:auto; }
    .tap-report-brand { display:flex; align-items:center; gap:10px; margin-bottom:36mm; }
    .tap-report-brand>span { width:38px; height:38px; border-radius:11px; display:grid; place-items:center; background:#087b76; color:#fff; font-weight:900; }
    .tap-report-brand b,.tap-report-brand small { display:block; }.tap-report-brand small{color:#53696b;font-size:10px}
    .tap-report-kicker { color:#087b76; font-size:11px; font-weight:900; letter-spacing:.12em; margin-bottom:9px; }
    h1 { font-size:32px; margin:0; letter-spacing:-1.3px; } h2 { font-size:23px; margin:0 0 8px; letter-spacing:-.8px; }
    .tap-report-lead,.tap-report-desc { color:#53696b; line-height:1.65; }.tap-report-lead{font-size:15px;max-width:145mm}.tap-report-desc{font-size:12px;margin:0 0 20px}
    .tap-report-meta { display:flex; gap:14px; margin:20px 0; padding:12px 0; border-top:1px solid #d8e4e2; border-bottom:1px solid #d8e4e2; font-size:11px; color:#53696b; }.tap-report-meta b{color:#102a2d;margin-right:auto}
    .tap-report-kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:9px; margin:21px 0; }.tap-report-kpis div{border:1px solid #d8e4e2;border-radius:13px;padding:13px}.tap-report-kpis b{display:block;font-size:20px}.tap-report-kpis span{font-size:10px;color:#53696b}
    .tap-report-summary { padding:18px; border-left:4px solid #087b76; background:#eff9f7; border-radius:8px; font-size:13px; line-height:1.65; }
    .tap-report-watermark { position:absolute; right:16mm; top:13mm; color:#963728; background:#fff0ec; border:1px solid #ffd0c8; border-radius:99px; padding:5px 9px; font-size:9px; font-weight:900; }
    footer { position:absolute; left:16mm; right:16mm; bottom:10mm; padding-top:8px; border-top:1px solid #d8e4e2; color:#708382; font-size:9px; }
    .tap-report-score-list { display:grid; gap:11px; }.tap-report-score-row{display:grid;grid-template-columns:42mm 1fr 12mm;gap:9px;align-items:center;padding:8px 0;border-bottom:1px solid #edf2f1}.tap-report-score-row b{display:block;font-size:12px}.tap-report-score-row small{font-size:9px;color:#53696b}.tap-report-score-row>strong{text-align:right;font-size:12px}.tap-report-bar{height:9px;background:#e8f0ef;border-radius:99px;overflow:hidden}.tap-report-bar i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#25c3b5,#087b76)}
    .tap-report-method,.tap-report-warning { display:flex; gap:12px; margin-top:18px; padding:13px 15px; border-radius:11px; background:#eff9f7; font-size:11px; }.tap-report-method b,.tap-report-warning b{min-width:24mm}.tap-report-method span,.tap-report-warning span{color:#53696b}.tap-report-warning{background:#fffaf0;border:1px solid #f1dfb5}
    .tap-report-priority-list{display:grid;gap:11px}.tap-report-priority{display:grid;grid-template-columns:28px 1fr auto;gap:11px;align-items:center;border:1px solid #d8e4e2;border-radius:14px;padding:14px}.tap-report-priority>span{width:28px;height:28px;border-radius:50%;display:grid;place-items:center;background:#087b76;color:#fff;font-weight:900}.tap-report-priority b,.tap-report-priority small{display:block}.tap-report-priority small{color:#53696b;margin-top:3px}.tap-report-priority em{font-style:normal;font-size:9px;color:#963728;background:#fff0ec;border-radius:99px;padding:5px 7px}
    .tap-report-table{width:100%;border-collapse:collapse;margin-top:16px}.tap-report-table th,.tap-report-table td{padding:9px 7px;border-bottom:1px solid #e7efee;font-size:10px;text-align:right}.tap-report-table th{background:#f7faf9;color:#53696b}.tap-report-table th:first-child,.tap-report-table td:first-child{text-align:left}
    .tap-report-method-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px;margin-top:18px}.tap-report-method-grid div{padding:12px;border:1px solid #d8e4e2;border-radius:11px}.tap-report-method-grid b,.tap-report-method-grid span{display:block}.tap-report-method-grid b{font-size:10px}.tap-report-method-grid span{font-size:9px;color:#53696b;margin-top:4px;line-height:1.45}
    @media print { body{background:#fff}.tap-report-document{padding:0}.tap-report-sheet{margin:0;box-shadow:none} }
    """
    return (
        "<!doctype html><html lang=\"ko\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{escape(str(model['project_name']))} 조직 교육수요 리포트</title><style>{css}</style></head>"
        f"<body><div class=\"tap-report-document\">{_report_body(model)}</div></body></html>"
    )
