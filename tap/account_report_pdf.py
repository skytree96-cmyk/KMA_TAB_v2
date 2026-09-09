"""Embedded-font, deterministic education pre/post PDF reports (no remote calls)."""
from __future__ import annotations

from datetime import datetime
from functools import lru_cache
from html import escape
from io import BytesIO
import math
from pathlib import Path
from statistics import mean
from threading import Lock
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as PDFTTFont
from reportlab.platypus import Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TEAL = colors.HexColor("#087b76")
INK = colors.HexColor("#103b37")
MUTED = colors.HexColor("#52716f")
PALE = colors.HexColor("#e8f5f2")
LINE = colors.HexColor("#dbe9e6")
PRE = colors.HexColor("#75beb3")
RULE_VERSION = "TAP-CHANGE-1.0"
_FONT_LOCK = Lock()


@lru_cache(maxsize=1)
def _fonts() -> tuple[str, str]:
    from fontTools.ttLib import TTFont
    with _FONT_LOCK:
        for name, filename in (("TAPMedium", "Paperlogy-5Medium.woff2"), ("TAPBold", "Paperlogy-8ExtraBold.woff2")):
            if name not in pdfmetrics.getRegisteredFontNames():
                font = TTFont(Path(__file__).resolve().parents[1] / "assets" / "fonts" / filename)
                font.flavor = None
                converted = BytesIO()
                font.save(converted)
                converted.seek(0)
                pdfmetrics.registerFont(PDFTTFont(name, converted))
                font.close()
        pdfmetrics.registerFontFamily("TAPMedium", normal="TAPMedium", bold="TAPBold", italic="TAPMedium", boldItalic="TAPBold")
    return "TAPMedium", "TAPBold"


def _score(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and 1 <= value <= 5 else None
    except (ValueError, TypeError):
        return None


def effect_level(change: float | None) -> str:
    if change is None or not math.isfinite(change):
        return "미산출"
    change = round(change, 4)
    if change >= 0.5:
        return "큰 향상"
    if change >= 0.2:
        return "향상"
    if change <= -0.2:
        return "하락"
    return "유지"


def prepare_rows(rows: list[Mapping[str, Any]], kind: str) -> list[dict[str, Any]]:
    if kind not in {"individual", "organization"}:
        raise ValueError("kind must be individual or organization")
    prepared = []
    for axis_number, raw in enumerate(rows, 1):
        row = dict(raw)
        row["_axis_number"] = axis_number
        try:
            n = max(0, int(row.get("valid_n", 0)))
        except (ValueError, TypeError, OverflowError):
            n = 0
        pre, post = _score(row.get("pre_score")), _score(row.get("post_score"))
        if kind == "organization" and n < 5:
            pre = post = None
        # Do not trust a caller-supplied difference or carry hidden scores into prose.
        row.update(pre_score=pre, post_score=post, valid_n=n,
                   change=round(post - pre, 2) if pre is not None and post is not None else None)
        row["factor_name_ko"] = str(row.get("factor_name_ko") or row.get("factor_code") or "역량")
        row["module_group"] = str(row.get("module_group") or "선택 역량")
        prepared.append(row)
    return prepared


def report_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    common = [r for r in rows if r.get("pre_score") is not None and r.get("post_score") is not None]
    pre = mean(r["pre_score"] for r in common) if common else None
    post = mean(r["post_score"] for r in common) if common else None
    delta = round(post - pre, 2) if common else None
    return {"pre": pre, "post": post, "change": delta, "effect": effect_level(delta),
            "valid_count": len(common), "selected_count": len(rows)}


def _guidance(row: Mapping[str, Any]) -> str:
    post, change = row.get("post_score"), row.get("change")
    if post is None or change is None:
        return "비교 가능한 응답이 부족합니다. 수행 기회와 응답 누락을 확인한 뒤, 다음 검사에서 동일한 행동 기준으로 응답해 주세요."
    if post >= 4.2:
        action = "교육 후 해당 행동이 높은 빈도로 보고되었습니다. 실제 적용 사례를 기록하고 다른 상황에서도 유지해 보세요."
    elif post >= 3.4:
        action = "교육 후 해당 행동이 비교적 자주 보고되었습니다. 주 1회 적용 사례를 돌아보며 반복 실천의 범위를 넓혀 보세요."
    elif post >= 2.6:
        action = "교육 후 해당 행동이 중간 빈도로 보고되었습니다. 한 가지 구체적인 실천 행동을 정해 업무 중 반복해 보세요."
    elif post >= 1.8:
        action = "교육 후 해당 행동이 낮은 빈도로 보고되었습니다. 행동을 적용할 수 있는 업무와 시점을 먼저 정해 보세요."
    else:
        action = "교육 후 해당 행동의 보고 빈도가 매우 낮습니다. 작은 실습 과제와 피드백을 통해 적용 기회를 마련해 보세요."
    change_tip = {"큰 향상": "증가한 행동이 유지되는지 후속 점검을 권장합니다.",
                  "향상": "개선된 행동의 구체적인 사례를 기록해 보세요.",
                  "유지": "변화 폭이 작으므로 수행 환경과 실천 목표를 함께 점검해 보세요.",
                  "하락": "업무 변화나 수행 기회 감소가 있었는지 먼저 확인해 보세요."}
    return action + " " + change_tip[effect_level(change)]


def _fmt(value: float | None, signed: bool = False) -> str:
    return "미산출" if value is None else (f"{value:+.2f}" if signed else f"{value:.2f}")


def _p(text: Any, *, size: float = 10, bold: bool = False, color=INK, align=0, leading: float | None = None) -> Paragraph:
    return Paragraph(escape(str(text)).replace("\n", "<br/>"), ParagraphStyle(
        "tap", fontName="TAPBold" if bold else "TAPMedium", fontSize=size,
        leading=leading or size * 1.48, textColor=color, wordWrap="CJK", alignment=align,
        spaceAfter=0, allowWidows=0, allowOrphans=0))


def _panel(items: list[Any], width: float, fill=colors.white, padding: float = 16) -> Table:
    table = Table([[items]], colWidths=[width], cornerRadii=[12, 12, 12, 12])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fill),
        ("BOX", (0, 0), (-1, -1), .6, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), padding), ("RIGHTPADDING", (0, 0), (-1, -1), padding),
        ("TOPPADDING", (0, 0), (-1, -1), padding), ("BOTTOMPADDING", (0, 0), (-1, -1), padding)]))
    return table


def _columns(left: Any, right: Any, widths: tuple[float, float], gap: float = 12) -> Table:
    table = Table([[left, "", right]], colWidths=[widths[0], gap, widths[1]])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return table


class Radar(Flowable):
    """All axes retained; missing observations create gaps, never zero scores."""
    def __init__(self, rows: list[Mapping[str, Any]], width: float = 280, height: float = 245):
        super().__init__()
        self.rows, self.width, self.height = rows, width, height

    def draw(self):
        c, n = self.canv, len(self.rows)
        if not n:
            empty = _p("선택한 역량이 없습니다.", color=MUTED)
            empty.wrap(self.width - 16, self.height)
            empty.drawOn(c, 8, self.height / 2)
            return
        cx, cy, radius = self.width / 2, self.height / 2 + 3, min(self.width * .275, 76)
        angles = [math.pi / 2 - 2 * math.pi * i / n for i in range(n)]
        point = lambda i, value: (cx + radius * value / 5 * math.cos(angles[i]), cy + radius * value / 5 * math.sin(angles[i]))
        for step in range(1, 6):
            c.setStrokeColor(LINE)
            c.setLineWidth(.55)
            if n >= 3:
                path = c.beginPath()
                path.moveTo(*point(0, step))
                for i in range(1, n):
                    path.lineTo(*point(i, step))
                path.close()
                c.drawPath(path)
            else:
                c.circle(cx, cy, radius * step / 5)
            c.setFont("TAPMedium", 7)
            c.setFillColor(MUTED)
            c.drawString(cx + 3, cy + radius * step / 5 - 3, str(step))
        for i, row in enumerate(self.rows):
            c.setStrokeColor(LINE)
            c.line(cx, cy, *point(i, 5))
            x = cx + (radius + 24) * math.cos(angles[i])
            y = cy + (radius + 24) * math.sin(angles[i])
            axis_name = row["factor_name_ko"] if len(row["factor_name_ko"]) <= 22 else f"역량 {row['_axis_number']:02d}"
            name = _p(axis_name, size=8.2, align=TA_CENTER, bold=True, leading=10.5)
            w = min(76, self.width / 3)
            _, h = name.wrap(w, 200)
            name.drawOn(c, max(0, min(self.width - w, x - w / 2)), y - h / 2)
        for key, color, dash in (("pre_score", PRE, [3, 2]), ("post_score", TEAL, [])):
            values = [row.get(key) for row in self.rows]
            c.setStrokeColor(color)
            c.setFillColor(color)
            c.setLineWidth(1.8)
            c.setDash(dash)
            if n >= 3 and all(value is not None for value in values):
                path = c.beginPath()
                path.moveTo(*point(0, values[0]))
                for i in range(1, n):
                    path.lineTo(*point(i, values[i]))
                path.close()
                c.saveState()
                c.setFillAlpha(.12 if key == "pre_score" else .07)
                c.drawPath(path, fill=1, stroke=1)
                c.restoreState()
            elif n >= 3:
                # Only adjacent valid axes join; do not bridge over missing values.
                for i in range(n):
                    j = (i + 1) % n
                    if values[i] is not None and values[j] is not None:
                        c.line(*point(i, values[i]), *point(j, values[j]))
            c.setDash([])
            for i, value in enumerate(values):
                if value is not None:
                    x, y = point(i, value)
                    c.circle(x, y, 2.4, stroke=0, fill=1)
        c.setFont("TAPMedium", 8)
        for x, text, color in ((self.width / 2 - 65, "교육 전", PRE), (self.width / 2 + 14, "교육 후", TEAL)):
            c.setFillColor(color)
            c.circle(x, 7, 3, fill=1, stroke=0)
            c.setFillColor(INK)
            c.drawString(x + 9, 4, text)


def _chart_groups(rows: list[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    if not rows:
        return [[]]
    group_count = math.ceil(len(rows) / 8)
    size = math.ceil(len(rows) / group_count)
    return [rows[i:i + size] for i in range(0, len(rows), size)]


def build_report_pdf(project: Mapping[str, Any], rows: list[Mapping[str, Any]], *, kind: str,
                     subject: str, participant_count: int = 1) -> bytes:
    prepared = prepare_rows(rows, kind)
    _fonts()
    summary = report_summary(prepared)
    output = BytesIO()
    page_w, page_h = A4
    width = page_w - 72
    config = project.get("config") or {}
    is_org = kind == "organization"
    label = "조직" if is_org else "개인"
    generated = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y.%m.%d")
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=36, leftMargin=36,
                            topMargin=39, bottomMargin=42, title=f"KMA TAP {label} 교육 전·후 리포트",
                            author="KMA TAP", pageCompression=1)
    story: list[Any] = [_p("KMA TAP.", size=20, bold=True, color=TEAL), Spacer(1, 5),
        _p(f"{label} 교육 전·후 리포트", size=22, bold=True), Spacer(1, 9),
        _p(f"{project.get('company_name') or '회원사'}  |  {project.get('name') or '교육 프로젝트'}", size=10, bold=True),
        _p(f"교육명 {config.get('course_name') or '-'}  ·  교육일 {config.get('training_date') or '-'}", size=9, color=MUTED),
        _p(f"보고 대상 {subject}" + (f"  ·  전·후 완료 {max(0, int(participant_count))}명" if is_org else ""), size=9, color=MUTED),
        Spacer(1, 15)]
    if summary["change"] is None:
        overview = "비교 가능한 역량 점수가 부족하여 교육 전·후 변화를 산출하지 않았습니다. 수행 기회와 유효응답을 확인해 주세요."
    else:
        overview = (f"비교 가능한 {summary['valid_count']}개 역량의 평균은 교육 전 {_fmt(summary['pre'])}점에서 "
                    f"교육 후 {_fmt(summary['post'])}점으로 {_fmt(summary['change'], True)}점 변화했습니다. "
                    f"운영 참고 기준상 '{summary['effect']}' 구간입니다. 실제 업무 적용 사례와 함께 해석해 주세요.")
    effect = _panel([_p("교육효과", size=11, bold=True), Spacer(1, 9),
                     _p(summary["effect"], size=25, bold=True, color=TEAL), Spacer(1, 5),
                     _p(f"평균 변화 {_fmt(summary['change'], True)}점" if summary["change"] is not None else "비교 점수 부족", size=10),
                     Spacer(1, 7), _p("자기보고 행동 변화", size=8, color=MUTED)], 155, PALE)
    overview_panel = _panel([_p("결과 총평", size=13, bold=True), Spacer(1, 9), _p(overview, size=10),
        Spacer(1, 7), _p(f"비교 가능 {summary['valid_count']} / 선택 {summary['selected_count']}개 역량 · 동일 가중 평균", size=8, color=MUTED)], width - 167)
    story.extend([_columns(effect, overview_panel, (155, width - 167)), Spacer(1, 13)])
    groups = _chart_groups(prepared)
    for index, group in enumerate(groups):
        if index:
            story.extend([PageBreak(), _p(f"역량 프로파일 {index + 1} / {len(groups)}", size=18, bold=True), Spacer(1, 16)])
        title = "선택 역량 프로파일" + (f"  {index + 1}/{len(groups)}" if len(groups) > 1 else "")
        radar_width = 302
        chart = _panel([_p(title, size=12, bold=True), Spacer(1, 3), Radar(group, radar_width - 28),
            Spacer(1, 5), _p("1~5점 척도 · 미산출 역량은 점·선 생략" + ("\n3개 미만 역량은 점으로 표시" if len(group) < 3 else ""), size=7.7, color=MUTED),
            *([_p("긴 역량명은 상세 결과의 번호로 표시합니다.", size=7.7, color=MUTED)] if any(len(r["factor_name_ko"]) > 22 for r in group) else [])], radar_width, padding=14)
        valid = [row for row in group if row.get("change") is not None]
        guide = [_p("업무 적용 가이드", size=12, bold=True), Spacer(1, 9)]
        if valid:
            strongest = max(valid, key=lambda r: r["post_score"])
            priority = min(valid, key=lambda r: (r["post_score"], r["change"]))
            guide.extend([_p("유지·확산할 역량", size=9, color=TEAL, bold=True),
                _p(strongest["factor_name_ko"] if len(strongest["factor_name_ko"]) <= 42 else f"역량 {strongest['_axis_number']:02d} (상세 결과 참조)", size=11, bold=True),
                _p(f"교육 후 {_fmt(strongest['post_score'])}점. 실천 사례를 기록하고 다른 업무에도 적용해 보세요.", size=9),
                Spacer(1, 14), _p("우선 점검할 역량", size=9, color=TEAL, bold=True),
                _p(priority["factor_name_ko"] if len(priority["factor_name_ko"]) <= 42 else f"역량 {priority['_axis_number']:02d} (상세 결과 참조)", size=11, bold=True),
                _p(_guidance(priority), size=9)])
        else:
            guide.append(_p("유효한 전·후 점수 확보 후 업무 적용 가이드를 확인할 수 있습니다.", size=9))
        story.extend([_columns(chart, _panel(guide, width - radar_width - 12), (radar_width, width - radar_width - 12)), Spacer(1, 12)])
    story.extend([_p("읽는 방법", size=10, bold=True), Spacer(1, 4),
        _p("교육효과는 동일 참여자·동일 문항의 자기보고 변화 요약이며 교육의 인과효과나 합격 판정이 아닙니다. "
           "수행 기회 없음(0)은 점수에서 제외합니다. 비교 가능한 역량에 동일 가중치를 적용하며, 미산출 역량은 평균에서 제외합니다.", size=8.2, color=MUTED),
        Spacer(1, 4), _p("변화량 기준: 큰 향상 ≥ +0.50 / 향상 +0.20 이상 +0.50 미만 / 유지 -0.20 초과 +0.20 미만 / 하락 ≤ -0.20. 운영 참고 기준, 인과효과 아님.", size=7.8, color=MUTED)])
    if prepared:
        story.extend([PageBreak(), _p("역량별 결과와 보완 가이드", size=20, bold=True), Spacer(1, 6),
            _p("각 역량의 전·후 변화와 교육 후 행동 빈도 구간에 따라 안내합니다.", size=9, color=MUTED), Spacer(1, 15)])
        for index, row in enumerate(prepared):
            hidden = is_org and row["valid_n"] < 5
            stats = "유효응답 5명 미만 · 점수 비공개" if hidden else (
                f"교육 전 {_fmt(row['pre_score'])}  →  교육 후 {_fmt(row['post_score'])}  |  변화 {_fmt(row['change'], True)}  |  {effect_level(row['change'])}")
            detail = [_p(f"{index + 1:02d}  {row['module_group']}", size=8, bold=True, color=TEAL), Spacer(1, 4),
                      _p(row["factor_name_ko"], size=13, bold=True), Spacer(1, 7), _p(stats, size=10, bold=True), Spacer(1, 7),
                      _p("해당 역량은 비교 가능한 참여자가 5명 미만이므로 점수와 평가를 공개하지 않습니다." if hidden else _guidance(row), size=9)]
            if is_org and not hidden:
                detail.extend([Spacer(1, 4), _p(f"전·후 유효 인원 {row['valid_n']}명", size=8, color=MUTED)])
            story.extend([_panel(detail, width), Spacer(1, 11)])
    story.extend([Spacer(1, 4), _p(f"평가 규칙 {RULE_VERSION} · 고정 구간에 따른 평가", size=7.5, color=MUTED),
        _p("교육 후 빈도 구간: 4.20 이상 / 3.40~4.19 / 2.60~3.39 / 1.80~2.59 / 1.00~1.79. 규준·합격 기준이 아닌 운영 참고 구간입니다.", size=7.5, color=MUTED)])

    def page(canvas, document):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#f2f7f6"))
        canvas.rect(0, 0, page_w, page_h, fill=1, stroke=0)
        canvas.setStrokeColor(LINE)
        canvas.line(36, 32, page_w - 36, 32)
        canvas.setFillColor(MUTED)
        canvas.setFont("TAPMedium", 7)
        canvas.drawString(36, 20, f"KMA TAP.  |  {generated}  |  {RULE_VERSION}")
        canvas.drawRightString(page_w - 36, 20, str(document.page))
        canvas.restoreState()

    doc.build(story, onFirstPage=page, onLaterPages=page)
    return output.getvalue()
