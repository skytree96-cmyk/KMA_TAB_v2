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
import unicodedata
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont as PDFTTFont
from reportlab.platypus import Flowable, HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TEAL = colors.HexColor("#1769ff")
INK = colors.HexColor("#161614")
MUTED = colors.HexColor("#6e6d66")
PALE = colors.HexColor("#eef3ff")
LINE = colors.HexColor("#e5e7eb")
PRE = colors.HexColor("#7f8da1")
WARN = colors.HexColor("#c2410c")       # a drop, or the distance still left to the target
WARN_PALE = colors.HexColor("#fff1e8")
WARN_SOFT = colors.HexColor("#e6b29e")  # the same warm hue, light enough to sit under the markers
FAINT = colors.HexColor("#9a9890")
GREY = colors.HexColor("#f3f4f6")
EFFECT_COLORS = {"크게 향상": (TEAL, colors.white), "향상": (PALE, TEAL), "유지": (GREY, MUTED), "하락": (WARN_PALE, WARN)}
RULE_VERSION = "TAP-CHANGE-1.0"
# One competency block is one unbreakable table: five long-titled courses stay well under one A4 frame.
COURSES_PER_BLOCK = 5
# Six required competencies plus optional ones is usually ten: one chart reads better than two halves.
RADAR_AXES = 12
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
        return "크게 향상"
    if change >= 0.2:
        return "향상"
    if change <= -0.2:
        return "하락"
    return "유지"


DEEP_GROUPS = {"specialty": "전문·미래", "job_function": "직무"}


@lru_cache(maxsize=1)
def _library_types() -> dict[str, str]:
    from tap.data import load_competencies
    return {str(row["factor_code"]): str(row.get("library_type") or "") for row in load_competencies()}


def _tier(row: Mapping[str, Any]) -> tuple[str, str]:
    """(tier, card label). Members are told "기본역량" and "심화역량", so the report says the same.

    The competency list decides the tier by library_type: base is 기본역량, the selectable libraries are
    심화역량. module_group stays the data key it is and only names the sub-group. A competency the list
    does not know keeps its module_group alone.
    """
    library = str(row.get("library_type") or _library_types().get(str(row.get("factor_code")), ""))
    group = str(row.get("module_group") or "")
    if library == "base":
        return "base", f"기본역량 · {group}" if group else "기본역량"
    if library:
        return "deep", f"심화역량 · {DEEP_GROUPS.get(library, group)}".removesuffix(" · ")
    return "", group or "역량"


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
        # Do not trust a caller-supplied difference or carry hidden scores into prose. The change is taken
        # from the two-decimal scores the report prints, so the three numbers on a card always add up.
        row.update(pre_score=pre, post_score=post, valid_n=n,
                   change=round(round(post, 2) - round(pre, 2), 2) if pre is not None and post is not None else None)
        row["factor_name_ko"] = str(row.get("factor_name_ko") or row.get("factor_code") or "역량")
        row["tier"], row["module_group"] = _tier(row)
        row["_hidden"] = kind == "organization" and n < 5
        prepared.append(row)
    return prepared


def report_summary(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    common = [r for r in rows if r.get("pre_score") is not None and r.get("post_score") is not None]
    pre = mean(r["pre_score"] for r in common) if common else None
    post = mean(r["post_score"] for r in common) if common else None
    delta = round(round(post, 2) - round(pre, 2), 2) if common else None
    return {"pre": pre, "post": post, "change": delta, "effect": effect_level(delta),
            "valid_count": len(common), "selected_count": len(rows)}


def _guidance(row: Mapping[str, Any]) -> str:
    post, change = row.get("post_score"), row.get("change")
    if post is None or change is None:
        return "비교할 수 있는 응답이 부족합니다. 수행 기회와 응답 누락 여부를 확인해 주세요."
    if post >= 4.2:
        action = "교육 후 행동 빈도가 높습니다. 다른 업무와 상황에도 넓혀 적용하세요."
    elif post >= 3.4:
        action = "교육 후 행동 빈도가 비교적 높습니다. 주 1회 적용 사례를 돌아보고 실천 범위를 넓히세요."
    elif post >= 2.6:
        action = "교육 후 행동 빈도가 중간 수준입니다. 구체적인 실천 행동 하나를 정해 업무에서 반복하세요."
    elif post >= 1.8:
        action = "교육 후 행동 빈도가 낮습니다. 이 행동을 적용할 업무와 시점부터 정하세요."
    else:
        action = "교육 후 행동 빈도가 매우 낮습니다. 작은 실습 과제와 피드백으로 적용 기회를 만드세요."
    change_tip = {"크게 향상": "늘어난 행동이 유지되는지 지켜보세요.",
                  "향상": "나아진 행동의 사례를 기록해 두세요.",
                  "유지": "변화 폭이 작습니다. 수행 환경과 실천 목표를 함께 점검하세요.",
                  "하락": "업무 변화나 수행 기회 감소가 있었는지 살펴보세요."}
    return action + " " + change_tip[effect_level(change)]


def _fmt(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "미산출"
    if signed and round(value, 2) == 0:
        return "0.00"  # not "+0.00" or "-0.00"
    return f"{value:+.2f}" if signed else f"{value:.2f}"


def _p(text: Any, *, size: float = 10, bold: bool = False, color=INK, align=0, leading: float | None = None,
       markup: bool = False) -> Paragraph:
    """``markup`` passes ReportLab tags through; the caller escapes any data it puts between them."""
    return Paragraph(str(text) if markup else escape(str(text)).replace("\n", "<br/>"), ParagraphStyle(
        "tap", fontName="TAPBold" if bold else "TAPMedium", fontSize=size,
        leading=leading or size * 1.48, textColor=color, alignment=align,
        spaceAfter=0, allowWidows=0, allowOrphans=0))


def _sentences(text: str, *, gap: float = 2.5, **style: Any) -> list[Any]:
    """One sentence per paragraph, so a narrow column reads as short lines and not as one block."""
    lines: list[Any] = []
    for sentence in text.replace(". ", ".\n").split("\n"):
        lines.extend([Spacer(1, gap), _p(sentence, **style)] if lines else [_p(sentence, **style)])
    return lines


_FLAT = [("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
         ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]


def _height(flowable: Flowable, width: float) -> float:
    return flowable.wrap(width, 100000)[1]


def _fit(text: str, font: str, size: float, width: float) -> str:
    """Cut a drawn label to the width it has."""
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while text and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "…"


class Chip(Flowable):
    """A small rounded label."""

    def __init__(self, text: str, fill=TEAL, color=colors.white, *, size: float = 7.6, stroke=None):
        super().__init__()
        self.text, self.fill, self.color, self.size, self.stroke = text, fill, color, size, stroke
        self.width = pdfmetrics.stringWidth(text, "TAPBold", size) + 13
        self.height = size + 7

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(self.fill)
        if self.stroke is not None:
            c.setStrokeColor(self.stroke)
            c.setLineWidth(.7)
        c.roundRect(0, 0, self.width, self.height, self.height / 2, stroke=int(self.stroke is not None), fill=1)
        c.setFillColor(self.color)
        c.setFont("TAPBold", self.size)
        c.drawCentredString(self.width / 2, (self.height - self.size) / 2 + 1.1, self.text)
        c.restoreState()


class NumberBadge(Flowable):
    """The running number of a course, so it reads as a list item and not as part of the title."""

    def __init__(self, number: int, size: float = 16):
        super().__init__()
        self.number, self.width, self.height = number, size, size

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(PALE)
        c.circle(self.width / 2, self.height / 2, self.width / 2, stroke=0, fill=1)
        c.setFillColor(TEAL)
        c.setFont("TAPBold", 8)
        c.drawCentredString(self.width / 2, self.height / 2 - 2.8, str(self.number))
        c.restoreState()


def _inline(first: Flowable, second: Any, width: float, gap: float = 7) -> Table:
    """A chip or badge with text on the same line."""
    table = Table([[first, second]], colWidths=[first.width + gap, width - first.width - gap])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), *_FLAT]))
    return table


class ScoreTrack(Flowable):
    """Pre and post scores on one 1~5 bar, their numbers beside it: pre on the left, post on the right.

    The stretch between the two markers is filled (teal up, warm down). With ``gap`` the stretch from the
    post score up to the target is filled instead: how far there is still to go. The target is a tick with
    its value above the bar. A missing score gets no marker and a dash for its number, never a point at zero.
    """

    def __init__(self, pre: float | None, post: float | None, target: float | None = None, *,
                 width: float = 280, height: float = 40, gap: bool = False, base=GREY, notch=colors.white):
        super().__init__()
        self.pre, self.post, self.target = pre, post, target
        self.width, self.height, self.gap, self.base, self.notch = width, height, gap, base, notch

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        c, pre, post, target = self.canv, self.pre, self.post, self.target
        side, y = 38, 16
        x0, x1 = side + 13, self.width - side - 13
        unit = (x1 - x0) / 4
        at = lambda value: x0 + unit * (value - 1)
        c.saveState()
        c.setLineCap(1)
        c.setLineWidth(7)
        c.setStrokeColor(self.base)
        c.line(x0, y, x1, y)
        if self.gap:
            if post is not None and target is not None and target > post:
                c.setStrokeColor(WARN_SOFT)
                c.line(at(post), y, at(target), y)
        elif pre is not None and post is not None and pre != post:
            c.setStrokeColor(PRE if post > pre else WARN_SOFT)
            c.line(at(pre), y, at(post), y)
        c.setLineCap(0)
        c.setStrokeColor(self.notch)
        c.setLineWidth(.9)
        for step in (2, 3, 4):
            c.line(at(step), y - 3.5, at(step), y + 3.5)
        c.setFont("TAPMedium", 6.2)
        c.setFillColor(FAINT)
        for step in range(1, 6):
            c.drawCentredString(at(step), y - 13.5, str(step))
        if target is not None:
            c.setStrokeColor(INK)
            c.setLineWidth(1.1)
            c.line(at(target), y - 6, at(target), y + 8.5)
            c.setFillColor(INK)
            c.setFont("TAPBold", 6.6)
            c.drawCentredString(at(target), y + 11.5, f"목표 {target:.2f}")
        if pre is not None:
            c.setFillColor(colors.white)
            c.setStrokeColor(PRE)
            c.setLineWidth(1.9)
            c.circle(at(pre), y, 4.1, stroke=1, fill=1)
        if post is not None:
            c.setFillColor(TEAL)
            c.setStrokeColor(colors.white)
            c.setLineWidth(1.4)
            c.circle(at(post), y, 5.4, stroke=1, fill=1)
        # The numbers sit beside the bar, each with the marker it belongs to.
        for value, label, right_aligned, ink in ((pre, "교육 전", True, MUTED), (post, "교육 후", False, INK)):
            label_width = pdfmetrics.stringWidth(label, "TAPMedium", 6.6)
            left = side - label_width - 8 if right_aligned else self.width - side
            if right_aligned:
                c.setFillColor(colors.white)
                c.setStrokeColor(PRE)
                c.setLineWidth(1.3)
                c.circle(left + 2.6, y + 7.6, 2.3, stroke=1, fill=1)
            else:
                c.setFillColor(TEAL)
                c.circle(left + 2.6, y + 7.6, 2.8, stroke=0, fill=1)
            c.setFillColor(MUTED)
            c.setFont("TAPMedium", 6.6)
            c.drawString(left + 8, y + 5.3, label)
            c.setFillColor(ink if value is not None else FAINT)
            c.setFont("TAPBold", 11.5)
            number = "-" if value is None else f"{value:.2f}"
            if right_aligned:
                c.drawRightString(side, y - 7.5, number)
            else:
                c.drawString(self.width - side, y - 7.5, number)
        c.restoreState()


class ChangeBars(Flowable):
    """Change per competency as bars from a zero line. A competency without a comparable score gets a word, not a bar."""

    def __init__(self, rows: list[Mapping[str, Any]], width: float, height: float, is_org: bool = False):
        super().__init__()
        self.rows, self.width, self.height, self.is_org = rows, width, height, is_org

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        c, pitch = self.canv, self.height / len(self.rows)
        name_width, value_width = self.width * .42, 30
        left, right = name_width + 6, self.width - value_width - 4
        changes = [row["change"] for row in self.rows if row.get("change") is not None]
        up, down = max([.5, *changes]), max([0.0, *(-value for value in changes)])
        scale = (right - left) / (up + down)
        zero = left + scale * down
        c.saveState()
        c.setStrokeColor(LINE)
        c.setLineWidth(.8)
        c.line(zero, 0, zero, self.height)
        for index, row in enumerate(self.rows):
            y = self.height - pitch * (index + .5)
            c.setFillColor(INK)
            c.setFont("TAPMedium", 7.8)
            c.drawString(0, y - 2.8, _fit(row["factor_name_ko"], "TAPMedium", 7.8, name_width))
            change = row.get("change")
            if change is None:
                c.setFillColor(MUTED)
                c.setFont("TAPMedium", 7.4)
                c.drawRightString(self.width, y - 2.7, "비공개" if self.is_org and row["valid_n"] < 5 else "미산출")
                continue
            color = {"하락": WARN, "유지": MUTED}.get(effect_level(change), TEAL)
            length, thickness = scale * abs(change), min(7, pitch - 4)
            c.setFillColor(color)
            if length > .4:
                c.roundRect(zero if change > 0 else zero - length, y - thickness / 2, length, thickness, min(2, length / 2), stroke=0, fill=1)
            c.setFont("TAPBold", 7.8)
            c.drawRightString(self.width, y - 2.8, _fmt(change, True))
        c.restoreState()


class LinkButton(Flowable):
    """A rounded teal button; its whole area opens the URL. The label says where it goes, for printed copies."""

    def __init__(self, text: str, url: str, *, width: float = 112, height: float = 22, size: float = 8.4):
        super().__init__()
        self.text, self.url, self.width, self.height, self.size = text, url, width, height, size

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(TEAL)
        c.roundRect(0, 0, self.width, self.height, self.height / 2, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("TAPBold", self.size)
        c.drawCentredString(self.width / 2, (self.height - self.size) / 2 + 1, self.text)
        c.linkURL(self.url, (0, 0, self.width, self.height), relative=1, thickness=0)
        c.restoreState()


def _button_row(button: LinkButton, text: str, width: float) -> Table:
    """A button with a muted explanation beside it."""
    table = Table([[button, _p(text, size=8, color=MUTED)]], colWidths=[button.width + 10, width - button.width - 10])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return table


def _panel(items: list[Any], width: float, fill=colors.white, padding: float = 16) -> Table:
    table = Table([[items]], colWidths=[width], cornerRadii=[12, 12, 12, 12])
    table.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), fill),
        ("BOX", (0, 0), (-1, -1), .6, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), padding), ("RIGHTPADDING", (0, 0), (-1, -1), padding),
        ("TOPPADDING", (0, 0), (-1, -1), padding), ("BOTTOMPADDING", (0, 0), (-1, -1), padding)]))
    return table


def _level_panels(left: list[Any], right: list[Any], widths: tuple[float, float], *, fills=(colors.white, colors.white),
                  paddings: tuple[float, float] = (16, 16)) -> Table:
    """Two panels side by side with the same height: the shorter one gets space at the bottom, not a ragged edge."""
    heights = [_height(_panel(items, width, fill, padding), width)
               for items, width, fill, padding in zip((left, right), widths, fills, paddings)]
    panels = [_panel(items + [Spacer(1, max(heights) - height)] if max(heights) - height > .5 else items, width, fill, padding)
              for items, width, fill, padding, height in zip((left, right), widths, fills, paddings, heights)]
    return _columns(panels[0], panels[1], widths)


class RatioBar(Flowable):
    """How many of the competencies, as a filled share of a thin bar."""

    def __init__(self, share: float, color, width: float, height: float = 4):
        super().__init__()
        self.share, self.color, self.width, self.height = max(0.0, min(1.0, share)), color, width, height

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFillColor(GREY)
        c.roundRect(0, 0, self.width, self.height, self.height / 2, stroke=0, fill=1)
        if self.share > 0:
            c.setFillColor(self.color)
            c.roundRect(0, 0, max(self.height, self.width * self.share), self.height, self.height / 2, stroke=0, fill=1)
        c.restoreState()


def _summary_tiles(rows: list[Mapping[str, Any]], targets: Mapping[str, Any], width: float) -> Table | None:
    """Counts across the comparable competencies: reached the target, improved, dropped, and the largest gain.

    Left out for fewer than two comparable competencies, where the headline already says everything.
    """
    valid = [row for row in rows if row.get("change") is not None]
    if len(valid) < 2:
        return None
    total, padding = len(valid), 9
    levels = [effect_level(row["change"]) for row in valid]
    row_targets = [_score(targets.get(str(row.get("factor_code")))) for row in valid]
    counts: list[tuple[str, int, Any]] = []
    if all(target is not None for target in row_targets):
        counts.append(("목표에 도달한 역량", sum(row["post_score"] >= target for row, target in zip(valid, row_targets)), TEAL))
    counts.extend([("향상한 역량", sum(level in ("크게 향상", "향상") for level in levels), TEAL),
                   ("하락한 역량", levels.count("하락"), WARN)])
    best = max(valid, key=lambda row: row["change"])
    tile_count = len(counts) + (best["change"] > 0)
    gap = 8
    tile_width = (width - gap * (tile_count - 1)) / tile_count
    inner = tile_width - 2 * padding
    tiles: list[list[Any]] = []
    for label, count, color in counts:
        ink = "#161614" if count == 0 else color.hexval().replace("0x", "#")
        tiles.append([_p(label, size=8, color=MUTED), Spacer(1, 2),
                      _p(f'<font color="{ink}">{count}</font><font name="TAPMedium" size="8.5" color="#6e6d66"> / {total}개</font>',
                         size=18, bold=True, leading=21, markup=True),
                      Spacer(1, 4), RatioBar(count / total, color, inner)])
    if best["change"] > 0:
        # Several competencies can share the largest gain; naming one alone would single it out wrongly.
        tied = sum(row["change"] == best["change"] for row in valid) - 1
        others = f" 외 {tied}개" if tied else ""
        name_room = inner - pdfmetrics.stringWidth(others, "TAPBold", 11.5)
        tiles.append([_p("가장 많이 오른 역량", size=8, color=MUTED), Spacer(1, 4),
                      _p(_fit(best["factor_name_ko"], "TAPBold", 11.5, name_room) + others, size=11.5, bold=True, leading=14),
                      Spacer(1, 2), _p(f"{_fmt(best['change'], True)}점", size=9.5, bold=True, color=TEAL)])
    heights = [_height(_panel(items, tile_width, padding=padding), tile_width) for items in tiles]
    cells: list[Any] = []
    for items, height in zip(tiles, heights):
        cells.extend([_panel(items + [Spacer(1, max(heights) - height)] if max(heights) - height > .5 else items, tile_width, padding=padding), ""])
    table = Table([cells[:-1]], colWidths=([tile_width, gap] * tile_count)[:-1])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), *_FLAT]))
    return table


def _change_legend(width: float) -> Table:
    """The one reading note on the first page: which change earns which label."""
    cells: list[Any] = [_p("※ 변화량 구간", size=7.8, bold=True, color=MUTED)]
    widths = [66.0]
    for level, span in (("크게 향상", "+0.50 이상"), ("향상", "+0.20~+0.49"), ("유지", "-0.19~+0.19"), ("하락", "-0.20 이하")):
        chip = Chip(level, *EFFECT_COLORS[level], size=6.8)
        cells.extend([chip, _p(span, size=7.8, color=MUTED)])
        widths.extend([chip.width + 5, pdfmetrics.stringWidth(span, "TAPMedium", 7.8) + 16])
    inner = width - 24
    row = Table([[*cells, ""]], colWidths=[*widths, max(0, inner - sum(widths))])
    row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), *_FLAT]))
    return _panel([row], width, padding=9)


def _columns(left: Any, right: Any, widths: tuple[float, float], gap: float = 12) -> Table:
    table = Table([[left, "", right]], colWidths=[widths[0], gap, widths[1]])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return table


class Radar(Flowable):
    """All axes retained. An axis without a score gets no point, never a zero: its label says so, and the
    line joins the scored axes on either side so the profile is always one closed shape."""
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
        for i, row in enumerate(self.rows):
            c.saveState()
            if row.get("pre_score") is None and row.get("post_score") is None:
                c.setStrokeColor(FAINT)
                c.setLineWidth(.7)
                c.setDash([2, 2.2])
            else:
                c.setStrokeColor(LINE)
            c.line(cx, cy, *point(i, 5))
            c.restoreState()
            x = cx + (radius + 24) * math.cos(angles[i])
            y = cy + (radius + 24) * math.sin(angles[i])
            axis_name = row["factor_name_ko"] if len(row["factor_name_ko"]) <= 22 else f"역량 {row['_axis_number']:02d}"
            pre_missing, post_missing = row.get("pre_score") is None, row.get("post_score") is None
            note = (("비공개" if row.get("_hidden") else "미산출") if pre_missing and post_missing
                    else "교육 전 미산출" if pre_missing else "교육 후 미산출" if post_missing else "")
            name = _p(escape(axis_name) + (f'<br/><font name="TAPMedium" size="6.8" color="#9a9890">({note})</font>' if note else ""),
                      size=8.2, align=TA_CENTER, bold=True, leading=10.5, color=FAINT if pre_missing and post_missing else INK, markup=True)
            w = min(76, self.width / 3)
            _, h = name.wrap(w, 200)
            name.drawOn(c, max(0, min(self.width - w, x - w / 2)), y - h / 2)
        for key, color, dash in (("pre_score", PRE, [3, 2]), ("post_score", TEAL, [])):
            values = [row.get(key) for row in self.rows]
            c.setStrokeColor(color)
            c.setFillColor(color)
            c.setLineWidth(1.8)
            c.setDash(dash)
            scored = [i for i, value in enumerate(values) if value is not None]
            if n >= 3 and len(scored) >= 3:
                # The shape runs through every axis that has a score and skips the ones that do not.
                path = c.beginPath()
                path.moveTo(*point(scored[0], values[scored[0]]))
                for i in scored[1:]:
                    path.lineTo(*point(i, values[i]))
                path.close()
                c.saveState()
                c.setLineJoin(1)
                c.setFillAlpha(.12 if key == "pre_score" else .07)
                c.drawPath(path, fill=1, stroke=1)
                c.restoreState()
            elif len(scored) == 2 and n >= 3:
                c.line(*point(scored[0], values[scored[0]]), *point(scored[1], values[scored[1]]))
            c.setDash([])
            for i, value in enumerate(values):
                if value is not None:
                    x, y = point(i, value)
                    c.circle(x, y, 2.4, stroke=0, fill=1)
        # Scale numbers go on last, between the first two axes: a data point only ever sits on an axis,
        # so a number can interrupt a line but never hide a score.
        between = math.pi / 2 - math.pi / n if n >= 3 else 0.0
        for step in range(1, 6):
            reach = radius * step / 5 * (math.cos(math.pi / n) if n >= 3 else 1)
            x, y = cx + reach * math.cos(between), cy + reach * math.sin(between)
            c.setFillColor(colors.white)
            c.circle(x, y, 3.3, stroke=0, fill=1)
            c.setFont("TAPMedium", 6.4)
            c.setFillColor(MUTED)
            c.drawCentredString(x, y - 2.2, str(step))
        c.setFont("TAPMedium", 8)
        for x, text, color in ((self.width / 2 - 65, "교육 전", PRE), (self.width / 2 + 14, "교육 후", TEAL)):
            c.setFillColor(color)
            c.circle(x, 7, 3, fill=1, stroke=0)
            c.setFillColor(INK)
            c.drawString(x + 9, 4, text)


def _missing_notice(rows: list[Mapping[str, Any]], width: float) -> Table | None:
    """Says, under the chart, which competencies have no score and that the shape skips them.

    Without it a reader sees a lopsided profile and cannot tell a low score from a missing one.
    """
    short = lambda row: row["factor_name_ko"] if len(row["factor_name_ko"]) <= 22 else f"역량 {row['_axis_number']:02d}"
    kinds: dict[str, list[str]] = {}
    for row in rows:
        pre_missing, post_missing = row.get("pre_score") is None, row.get("post_score") is None
        kind = (("비공개" if row.get("_hidden") else "미산출") if pre_missing and post_missing
                else "교육 전 미산출" if pre_missing else "교육 후 미산출" if post_missing else "")
        if kind:
            kinds.setdefault(kind, []).append(short(row))
    if not kinds:
        return None
    # Kept to a chip line and one sentence per reason: the box has to fit beside the guide without pushing
    # the summary tiles off the first page.
    padding = 6
    inner = width - 2 * padding
    items: list[Any] = []
    for kind, names in kinds.items():
        items.extend([_inline(Chip(kind, colors.white, MUTED, size=6.6, stroke=FAINT), _p(", ".join(names), size=7.8, bold=True), inner, gap=6),
                      Spacer(1, 2)])
    if any(kind != "비공개" for kind in kinds):
        items.append(_p("점수가 없어('수행 기회 없음' 등) 도형에서 건너뛰었습니다.", size=7.2, color=MUTED))
    if "비공개" in kinds:
        items.append(_p("유효응답 5명 미만이라 공개하지 않고 도형에서 건너뛰었습니다.", size=7.2, color=MUTED))
    return _panel(items, width, GREY, padding=padding)


HEAT_ROWS_PER_PANEL = 14   # departments on one grid; more continue in the next box
HEAT_COLUMNS = 12          # competencies across one grid


def _heat_color(score: float):
    """1 is almost white, 5 is the brand blue: darker means a higher post-training mean."""
    share = max(0.0, min(1.0, (score - 1) / 4))
    low, high = (0xf2, 0xf6, 0xff), (0x0b, 0x4f, 0xcc)
    return colors.Color(*((a + (b - a) * share) / 255 for a, b in zip(low, high))), share


class HeatGrid(Flowable):
    """Departments down, competencies across. A cell holds the post mean and, smaller, the change.

    A cell that is not shown says so in words and stays grey, so it is never read as a low score.
    A department with nothing to show keeps its row: one grey bar with the reason (row["note"]).
    """
    LABEL, ROW, GAP = 96, 30, 3

    def __init__(self, factors: list[Mapping[str, Any]], rows: list[Mapping[str, Any]], width: float, names: Mapping[str, str]):
        super().__init__()
        self.factors, self.rows, self.width = factors, rows, width
        self.cell = (width - self.LABEL) / max(1, len(factors))
        self.heads = [_p(names.get(str(factor["factor_code"]), str(factor["factor_name_ko"])), size=6.6, bold=True, color=MUTED,
                         align=TA_CENTER, leading=8.2) for factor in factors]
        self.head_height = max((head.wrap(self.cell - 4, 200)[1] for head in self.heads), default=0)
        # The organization row, when there is one, stands a little apart from the departments.
        self.split = 6 if rows and rows[0].get("total") else 0
        self.height = self.head_height + 6 + len(rows) * self.ROW + self.split

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        for index, head in enumerate(self.heads):
            head.wrap(self.cell - 4, 200)
            head.drawOn(c, self.LABEL + index * self.cell + 2, self.height - self.head_height)
        top = self.height - self.head_height - 6
        for position, row in enumerate(self.rows):
            y = top - (position + 1) * self.ROW - (self.split if position else 0)
            middle = y + self.ROW / 2
            total = bool(row.get("total"))
            c.setFillColor(TEAL if total else INK)
            c.setFont("TAPBold", 8.2)
            c.drawString(0, middle + 1.5, _fit(str(row["team"]), "TAPBold", 8.2, self.LABEL - 8))
            c.setFillColor(MUTED)
            c.setFont("TAPMedium", 6.6)
            c.drawString(0, middle - 8, f"{row['paired_n']}명")
            if row.get("note"):
                across = self.cell * len(row["cells"]) - self.GAP
                c.setFillColor(GREY)
                c.roundRect(self.LABEL + self.GAP / 2, y + self.GAP / 2, across, self.ROW - self.GAP, 4, stroke=0, fill=1)
                c.setFillColor(MUTED)
                c.setFont("TAPMedium", 7.4)
                c.drawString(self.LABEL + self.GAP / 2 + 10, middle - 2.6, _fit(str(row["note"]), "TAPMedium", 7.4, across - 20))
                continue
            for index, cell in enumerate(row["cells"]):
                x, width, height = self.LABEL + index * self.cell + self.GAP / 2, self.cell - self.GAP, self.ROW - self.GAP
                centre = x + width / 2
                if cell.get("shown") and cell.get("post_mean") is not None:
                    fill, share = _heat_color(float(cell["post_mean"]))
                    dark = share >= .7  # white text only where the teal is deep enough to carry it
                    c.setFillColor(fill)
                    c.roundRect(x, y + self.GAP / 2, width, height, 4, stroke=0, fill=1)
                    c.setFillColor(colors.white if dark else INK)
                    c.setFont("TAPBold", 9)
                    c.drawCentredString(centre, middle + .5, f"{float(cell['post_mean']):.2f}")
                    change = cell.get("change")
                    if change is not None:
                        # The warm colour for a drop only reads on a pale cell; on a mid teal the minus sign carries it.
                        c.setFillColor(colors.white if dark else WARN if share < .4 and effect_level(change) == "하락" else INK)
                        c.setFont("TAPMedium", 6.4)
                        c.drawCentredString(centre, middle - 8.5, _fmt(float(change), True))
                else:
                    c.setFillColor(GREY)
                    c.roundRect(x, y + self.GAP / 2, width, height, 4, stroke=0, fill=1)
                    c.setFillColor(FAINT)
                    c.setFont("TAPMedium", 6.4)
                    c.drawCentredString(centre, middle - 2.2, "비공개" if cell.get("paired_n") else "응답 없음")
        c.restoreState()


class HeatLegend(Flowable):
    """The colour scale of the heat grid and the grey of a cell that is not shown."""

    def __init__(self, width: float, height: float = 12):
        super().__init__()
        self.width, self.height = width, height

    def wrap(self, available_width, available_height):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.setFont("TAPMedium", 7)
        c.setFillColor(MUTED)
        c.drawString(0, 2.5, "교육 후 평균  1점")
        x = pdfmetrics.stringWidth("교육 후 평균  1점", "TAPMedium", 7) + 6
        for step in range(9):
            c.setFillColor(_heat_color(1 + step / 2)[0])
            c.rect(x + step * 13, 1, 13.4, 9, stroke=0, fill=1)
        x += 9 * 13 + 6
        c.setFillColor(MUTED)
        c.drawString(x, 2.5, "5점")
        x += pdfmetrics.stringWidth("5점", "TAPMedium", 7) + 18
        c.setFillColor(GREY)
        c.roundRect(x, 1, 18, 9, 2, stroke=0, fill=1)
        c.setFillColor(MUTED)
        c.drawString(x + 23, 2.5, "비공개")
        c.restoreState()


def _heatmap_story(heatmap: Mapping[str, Any] | None, prepared: list[Mapping[str, Any]], width: float) -> list[Any]:
    """The department page of the organization report, from account_insights.team_heatmap.

    Drawn when people are split over two or more departments and at least one of them has a number to show.
    One department would repeat the organization result. A department hidden as a whole stays on the grid
    with the reason, as on the screen: left out, its members would only wonder where it went.
    """
    from tap.account_insights import hidden_team_note
    factors = list((heatmap or {}).get("factors") or [])
    teams = [{**row, "note": hidden_team_note(row)} for row in (heatmap or {}).get("rows") or [] if row.get("paired_n")]
    if not factors or len(teams) < 2 or all(team["note"] for team in teams):
        return []
    by_code = {str(row.get("factor_code")): row for row in prepared}
    # Column heads follow the radar: a long name becomes the competency's number on the details page.
    names = {code: f"역량 {row['_axis_number']:02d}" for code, row in by_code.items() if len(row["factor_name_ko"]) > 22}
    total = {"team": "조직 전체", "total": True,
             "paired_n": max((int(row.get("valid_n") or 0) for row in prepared), default=0),
             "cells": [{"paired_n": int((by_code.get(str(factor["factor_code"])) or {}).get("valid_n") or 0),
                        "shown": (by_code.get(str(factor["factor_code"])) or {}).get("post_score") is not None,
                        "post_mean": (by_code.get(str(factor["factor_code"])) or {}).get("post_score"),
                        "change": (by_code.get(str(factor["factor_code"])) or {}).get("change")} for factor in factors]}
    lead: list[Any] = [Spacer(1, 6), _p("팀(부서)별 교육 후 평균", size=20, bold=True), Spacer(1, 6),
                       _p("부서마다 역량별 교육 후 평균을 나란히 놓았습니다. 색이 진할수록 점수가 높습니다.\n"
                          "칸의 큰 숫자는 교육 후 평균(1~5점), 작은 숫자는 교육 전과 비교한 변화입니다.", size=9, color=MUTED),
                       Spacer(1, 12)]
    story: list[Any] = []
    inner = width - 28
    for column in range(0, len(factors), HEAT_COLUMNS):
        picked = slice(column, column + HEAT_COLUMNS)
        for offset in range(0, len(teams), HEAT_ROWS_PER_PANEL):
            rows = [{**row, "cells": row["cells"][picked]} for row in (total, *teams[offset:offset + HEAT_ROWS_PER_PANEL])]
            grid = _panel([HeatGrid(factors[picked], rows, inner, names), Spacer(1, 10), HeatLegend(inner)], width, padding=14)
            story.extend([KeepTogether(lead + [grid]), Spacer(1, 9)])
            lead = []
    story.extend([_p("※ 비공개는 교육 전후 유효응답이 5명 미만인 칸입니다. 한 역량에서 한 부서만 가려지면 조직 평균으로 그 값을 "
                     "계산해 낼 수 있어, 인원이 가장 적은 부서의 칸도 함께 가립니다.", size=7.5, color=MUTED), Spacer(1, 6)])
    return story


def _chart_groups(rows: list[Mapping[str, Any]]) -> list[list[Mapping[str, Any]]]:
    if not rows:
        return [[]]
    group_count = math.ceil(len(rows) / RADAR_AXES)
    size = math.ceil(len(rows) / group_count)
    return [rows[i:i + size] for i in range(0, len(rows), size)]


SOURCE_LABELS = {"public_edu_center": "공개교육", "studio_elearning": "이러닝", "b2b_inquiry": "단체교육 문의", "studio_original": "stud.io"}
BUTTON_LABELS = {"public_edu_center": "최신 일정 보기", "studio_elearning": "수강 페이지 보기", "b2b_inquiry": "과정 안내 보기"}


SOURCE_COLORS = {"public_edu_center": "#1769ff", "studio_elearning": "#3d5f94", "b2b_inquiry": "#8a5a14"}


def _course_entry(index: int, course: Mapping[str, Any], width: float) -> Table:
    """One course: number badge, title over a coloured source and its schedule, the link button on the right."""
    source = str(course.get("source", ""))
    label = SOURCE_LABELS.get(source) or course.get("delivery_label")
    meta = [f'<font name="TAPBold" color="{SOURCE_COLORS.get(source, "#6e6d66")}">{escape(str(label))}</font>'] if label else []
    if course.get("schedule"):
        meta.append(escape(str(course["schedule"])))
    body: list[Any] = [_p(unicodedata.normalize("NFKC", str(course["title"])), size=10.2, bold=True)]
    if meta:
        body.extend([Spacer(1, 2), _p("  ·  ".join(meta), size=8.4, color=MUTED, markup=True)])
    url = str(course.get("url") or "")
    button_width = 118
    right: Any = LinkButton(BUTTON_LABELS.get(source, "KMA에서 과정 찾기"), url, width=button_width) if url.startswith(("https://", "http://")) else ""
    table = Table([[NumberBadge(index), body, right]], colWidths=[24, width - button_width - 34, button_width + 10])
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), *_FLAT, ("LEFTPADDING", (2, 0), (2, 0), 10)]))
    return table


def _competency_blocks(name: str, group: list[Mapping[str, Any]], first_index: int, width: float) -> list[Table]:
    """One competency as one box: a tinted band with the scores behind the pick, then its courses on white.

    The band says why this competency was picked and the white rows say what to take, so the two never
    read as one list. A box is a single unbreakable table; a long course list continues in a second box.
    """
    inner = width - 32
    first = group[0]
    blocks = []
    for offset in range(0, len(group), COURSES_PER_BLOCK):
        if offset:
            band: list[Any] = [_p(f"{name}  ·  추천 과정 이어서", size=10.5, bold=True)]
        else:
            advice = next((str(course["advice"]) for course in group if course.get("advice")), "")
            words: list[Any] = [_inline(Chip("응답 결과"), _p(name, size=12, bold=True), inner),
                                *([Spacer(1, 5), _p(first["reason"], size=8.6, bold=True, color=TEAL)] if first.get("reason") else []),
                                *([Spacer(1, 3), _p(advice, size=8.6)] if advice else [])]
            score, target = _score(first.get("score")), _score(first.get("target"))
            if score is None or target is None:
                band = words
            else:
                change = first.get("change")
                track_width = 214
                words[0] = _inline(Chip("응답 결과"), _p(name, size=12, bold=True), inner - track_width - 12)
                picture = Table([[words, ScoreTrack(None if change is None else _score(score - float(change)), score, target,
                                                    width=track_width, gap=True, base=colors.white, notch=PALE)]],
                                colWidths=[inner - track_width - 12, track_width + 12])
                picture.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), *_FLAT, ("LEFTPADDING", (1, 0), (1, 0), 12)]))
                band = [picture]
        rows: list[Any] = [Chip("추천 과정", colors.white, TEAL, stroke=TEAL)]
        for position, course in enumerate(group[offset:offset + COURSES_PER_BLOCK]):
            rows.extend([Spacer(1, 7), HRFlowable(width="100%", thickness=.5, color=LINE, spaceBefore=0, spaceAfter=0), Spacer(1, 7)]
                        if position else [Spacer(1, 8)])
            rows.append(_course_entry(first_index + offset + position, course, inner))
        block = Table([[band], [rows]], colWidths=[width], cornerRadii=[12, 12, 12, 12])
        block.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, 0), PALE), ("BACKGROUND", (0, 1), (0, 1), colors.white),
            ("BOX", (0, 0), (-1, -1), .6, LINE), ("LINEBELOW", (0, 0), (0, 0), .6, LINE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 16), ("RIGHTPADDING", (0, 0), (-1, -1), 16),
            ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10)]))
        blocks.append(block)
    return blocks


def _competency_card(index: int, row: Mapping[str, Any], width: float, *, is_org: bool, target: float | None) -> Table:
    """One competency on the details page: name, effect chip and change on the left, the 1~5 track on the right."""
    padding = 12
    inner = width - 2 * padding
    hidden = is_org and row["valid_n"] < 5
    level = "비공개" if hidden else effect_level(row["change"])
    fill, ink = EFFECT_COLORS.get(level, (GREY, MUTED))
    # The organization's respondent count rides on the label line: a line of its own cost each card a row.
    counted = f'<font name="TAPMedium" color="#6e6d66">  ·  유효 인원 {row["valid_n"]}명</font>' if is_org and not hidden else ""
    name = [_p(escape(f"{index:02d}  {row['module_group']}") + counted, size=8, bold=True, color=TEAL, markup=True), Spacer(1, 3),
            _p(row["factor_name_ko"], size=13, bold=True)]
    if hidden:
        result: list[Any] = [Chip(level, fill, ink)]
        widths = [inner * .8, 0, inner * .2]
        advice = "개인 응답이 드러나지 않도록 점수와 평가를 공개하지 않습니다."
    else:
        result = [_p('<font name="TAPMedium" size="8" color="#6e6d66">변화 </font>' + _fmt(row["change"], True), size=16, bold=True,
                     color=WARN if level == "하락" else INK, align=TA_RIGHT, leading=18, markup=True) if row["change"] is not None
                  else _p("비교 점수 부족", size=8.6, color=MUTED, align=TA_RIGHT), Spacer(1, 4), Chip(level, fill, ink)]
        widths = [inner * .32, inner * .5, inner * .18]
        advice = _guidance(row)
    top = Table([[name, "" if hidden else ScoreTrack(row["pre_score"], row["post_score"], target, width=widths[1] - 12), result]],
                colWidths=widths)
    top.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), *_FLAT, ("LEFTPADDING", (1, 0), (1, 0), 6), ("ALIGN", (2, 0), (2, 0), "RIGHT")]))
    detail = [top, Spacer(1, 6), HRFlowable(width="100%", thickness=.5, color=LINE, spaceBefore=0, spaceAfter=0), Spacer(1, 6),
              _p(advice, size=9)]
    return _panel(detail, width, padding=padding)


def _followup_story(transfer: Mapping[str, Any] | None, courses: list[Mapping[str, Any]] | None, width: float) -> list[Any]:
    """Transfer climate (organization only) and follow-up courses, continuing after the competency details."""
    from tap.account_insights import COURSE_INQUIRY_URL, course_context_note, transfer_notes
    is_org = transfer is not None
    inner = width - 32  # panel padding
    inquiry = [_button_row(LinkButton("맞춤형 교육 문의", COURSE_INQUIRY_URL, width=108),
                           "회사 상황에 맞춘 과정은 KMA 교육 문의 페이지(www.kma.or.kr)로 문의 부탁드립니다.", inner)] if is_org else []
    # `lead` waits for the next box so a heading never ends a page on its own.
    lead: list[Any] = [Spacer(1, 6), _p("현업전이 환경과 후속 과정" if is_org else "보완 학습 제안", size=20, bold=True), Spacer(1, 6),
                       _p("현업 적용 여건과 다음 교육에서 검토할 KMA 과정입니다." if is_org else "본인 응답(자기보고)에 근거한 제안입니다.",
                          size=9, color=MUTED), Spacer(1, 15 if is_org else 3)]
    story: list[Any] = []
    if transfer is not None:
        if transfer.get("disclosed"):
            cells = [[_p(row["label"], size=8.5, color=MUTED), _p(f"{row['mean']:.2f}", size=17, bold=True, color=TEAL)]
                     for row in transfer["factors"]]
            grid = Table([cells], colWidths=[(width - 32) / 4] * 4)
            grid.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            barriers = Table([[_p(row["label"], size=8.6), _p(f"{row['count']}명", size=8.6, align=2), _p(f"{row['rate']}%", size=8.6, bold=True, align=2)]
                              for row in transfer["barriers"]], colWidths=[width - 172, 60, 60])
            barriers.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -2), .4, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                          ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
            body = [_p(f"현업전이 환경  ·  교육 후 검사 응답 {transfer['n']}명 평균(1~5)", size=12, bold=True), Spacer(1, 9), grid,
                    Spacer(1, 10), _p("적용 장애요인(복수 선택)", size=9, bold=True, color=TEAL), Spacer(1, 3), barriers,
                    Spacer(1, 9), *[_p("· " + note, size=9) for note in transfer_notes(transfer)]]
        else:
            body = [_p("현업전이 환경", size=12, bold=True), Spacer(1, 7),
                    _p(f"교육 후 현업전이 응답이 5명 미만({transfer.get('n', 0)}명)이라 평균과 장애요인을 공개하지 않습니다.", size=9)]
        story.extend([KeepTogether(lead + [_panel(body, width)]), Spacer(1, 12)])
        lead = []
    if courses:
        note = course_context_note(transfer)
        sources = "공개교육, 이러닝, 단체교육 문의" if is_org else "공개교육과 이러닝"
        lead.extend([*([_p("교육과정 검토 우선순위", size=12, bold=True), Spacer(1, 4)] if is_org else []),
                     _p(f"교육 후 {'평균이' if is_org else '점수가'} 목표보다 0.2점 이상 낮은 역량을 차이가 큰 순서로 골랐습니다.\n"
                        f"역량마다 {sources} 과정을 제안합니다. 버튼을 누르면 KMA 과정 페이지가 열립니다.", size=8.4, color=MUTED),
                     *([Spacer(1, 6), _p(note, size=8.8, bold=True, color=TEAL)] if note else []), Spacer(1, 10)])
        # Courses arrive source by source; the reader needs them under their competency, each competency in one box.
        groups: dict[str, list[Mapping[str, Any]]] = {}
        for course in courses:
            groups.setdefault(str(course["factor_name_ko"]), []).append(course)
        index, blocks = 1, []
        for name, group in groups.items():
            blocks.extend(_competency_blocks(name, group, index, width))
            index += len(group)
        for block in blocks:
            story.extend([KeepTogether(lead + [block]), Spacer(1, 9)])
            lead = []
        if inquiry:
            story.append(_panel(inquiry, width, padding=12))
    elif courses is not None:
        story.append(KeepTogether(lead + [_panel([_p("교육과정 검토 우선순위" if is_org else "제안 과정", size=12, bold=True), Spacer(1, 7),
                                                  _p("목표보다 0.2점 이상 낮은 역량이 없어 검토할 후속 과정이 없습니다.", size=9),
                                                  *([Spacer(1, 10), *inquiry] if inquiry else [])], width)]))
        lead = []
    # No forced page break: the heading travels with its first box, so a half-empty page is filled first.
    return [*story, *lead]


def build_report_pdf(project: Mapping[str, Any], rows: list[Mapping[str, Any]], *, kind: str,
                     subject: str, participant_count: int = 1, transfer: Mapping[str, Any] | None = None,
                     courses: list[Mapping[str, Any]] | None = None, heatmap: Mapping[str, Any] | None = None) -> bytes:
    """``heatmap`` is account_insights.team_heatmap's result; it adds the department grid to an organization report."""
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
                            topMargin=39, bottomMargin=42, title=f"KMA TAP {label} 교육 전후 리포트",
                            author="KMA TAP", pageCompression=1)
    story: list[Any] = [_p("KMA TAP.", size=20, bold=True, color=TEAL), Spacer(1, 5),
        _p(f"{label} 교육 전후 리포트", size=22, bold=True), Spacer(1, 9),
        _p(f"{project.get('company_name') or '회원사'}  |  {project.get('name') or '교육 프로젝트'}", size=10, bold=True),
        _p(f"교육명 {config.get('course_name') or '-'}  ·  교육일 {config.get('training_date') or '-'}", size=9, color=MUTED),
        _p(f"보고 대상 {subject}" + (f"  ·  교육 전후 완료 {max(0, int(participant_count))}명" if is_org else ""), size=9, color=MUTED),
        Spacer(1, 15)]
    if summary["change"] is None:
        overview = "비교할 수 있는 역량 점수가 부족해 교육 전후 변화를 산출하지 않았습니다."
    else:
        change = summary["change"]
        # Direction in words: "+0.00점 변화했습니다" is not a sentence a reader can use.
        single = summary["valid_count"] == 1
        average = "비교 가능한 역량 1개의 점수" if single else f"비교 가능한 {summary['valid_count']}개 역량의 평균"
        overview = (f"{average}{'는' if single else '은'} 교육 전후 모두 {_fmt(summary['pre'])}점입니다.\n변화량 구간은 '{summary['effect']}'입니다." if change == 0 else
                    f"{average}{'가' if single else '이'} {abs(change):.2f}점 {'올랐습니다' if change > 0 else '내려갔습니다'}.\n"
                    f"교육 전 {_fmt(summary['pre'])}점, 교육 후 {_fmt(summary['post'])}점으로 '{summary['effect']}' 구간입니다.")
        overview += "\n업무 적용 사례와 함께 해석해 주세요."
    effect = [_p("교육효과", size=11, bold=True), Spacer(1, 9),
              _p(summary["effect"], size=25, bold=True, color=TEAL), Spacer(1, 5),
              _p(f"평균 변화 {_fmt(summary['change'], True)}점" if summary["change"] is not None else "비교 점수 부족", size=10),
              Spacer(1, 7), _p("자기보고 행동 변화", size=8, color=MUTED)]
    first_line, *more_lines = overview.split("\n")
    overview_items = [_p("결과 총평", size=13, bold=True), Spacer(1, 9), _p(first_line, size=10.5, bold=True),
        *[flowable for line in more_lines for flowable in (Spacer(1, 3), _p(line, size=9.6))],
        Spacer(1, 8), _p(f"비교 가능 {summary['valid_count']} / 전체 {summary['selected_count']}개 역량 · 동일 가중 평균", size=8, color=MUTED)]
    story.extend([_level_panels(effect, overview_items, (155, width - 167), fills=(PALE, colors.white)), Spacer(1, 9)])
    tiles = _summary_tiles(prepared, config.get("target_means") or {}, width)
    tiles_at = len(story)
    if tiles is not None:
        story.extend([tiles, Spacer(1, 9)])
    groups = _chart_groups(prepared)
    for index, group in enumerate(groups):
        if index:
            story.extend([PageBreak(), _p(f"역량 프로파일 {index + 1} / {len(groups)}", size=18, bold=True), Spacer(1, 16)])
        # A chart of only selectable competencies says so; with the required ones in it, it is simply the profile.
        only_deep = bool(group) and all(row["tier"] == "deep" for row in group)
        title = ("심화역량 프로파일" if only_deep else "역량 프로파일") + (f"  {index + 1}/{len(groups)}" if len(groups) > 1 else "")
        radar_width = 302
        notice = _missing_notice(group, radar_width - 28)
        chart_items = lambda radar_height: [_p(title, size=12, bold=True), Spacer(1, 3), Radar(group, radar_width - 28, radar_height),
            Spacer(1, 5), _p("1~5점 척도" + (" · 역량이 3개 미만이면 점으로 표시" if len(group) < 3 else ""), size=7.7, color=MUTED),
            *([Spacer(1, 4), notice] if notice is not None else []),
            *([_p("긴 역량명은 상세 결과의 번호로 표시합니다.", size=7.7, color=MUTED)] if any(len(r["factor_name_ko"]) > 22 for r in group) else [])]
        chart = chart_items(245)
        valid = [row for row in group if row.get("change") is not None]
        guide = [_p("업무 적용 가이드", size=12, bold=True), Spacer(1, 9)]
        short_name = lambda r: r["factor_name_ko"] if len(r["factor_name_ko"]) <= 42 else f"역량 {r['_axis_number']:02d} (상세 결과 참조)"
        if len(valid) == 1:
            # One comparable competency cannot be both the one to spread and the one to check first.
            guide.extend([_p("비교 가능한 역량", size=9, color=TEAL, bold=True),
                _p(short_name(valid[0]), size=11, bold=True), Spacer(1, 3), *_sentences(_guidance(valid[0]), size=9)])
        elif valid:
            priority = min(valid, key=lambda r: (r["post_score"], r["change"]))
            strongest = max((r for r in valid if r is not priority), key=lambda r: r["post_score"])
            guide.extend([_p("유지·확산할 역량", size=9, color=TEAL, bold=True),
                _p(short_name(strongest), size=11, bold=True),
                Spacer(1, 3), *_sentences(f"교육 후 {_fmt(strongest['post_score'])}점입니다. 실천 사례를 다른 업무에도 적용하세요.", size=9),
                Spacer(1, 10), _p("우선 점검할 역량", size=9, color=TEAL, bold=True),
                _p(short_name(priority), size=11, bold=True),
                Spacer(1, 3), *_sentences(_guidance(priority), size=9)])
        else:
            guide.append(_p("비교할 수 있는 교육 전후 점수가 없어 가이드를 표시하지 않습니다.", size=9))
        guide_width = width - radar_width - 12
        if group:
            # The guide is shorter than the chart beside it; the change per competency fills the rest of the box.
            def with_bars(height: float) -> list[Any]:
                return [*guide, Spacer(1, 9), HRFlowable(width="100%", thickness=.6, color=LINE, spaceBefore=0, spaceAfter=0),
                        Spacer(1, 8), _p("역량별 변화", size=9, color=TEAL, bold=True), Spacer(1, 5),
                        ChangeBars(group, guide_width - 32, height, is_org)]
            tight = len(group) * (11 if len(group) <= 8 else 10)
            room = _height(_panel(chart, radar_width, padding=14), radar_width) - _height(_panel(with_bars(tight), guide_width), guide_width)
            guide = with_bars(tight + max(0, min(room, len(group) * 7)))
        taller = _height(_panel(guide, guide_width), guide_width) - _height(_panel(chart, radar_width, padding=14), radar_width)
        if taller > .5:
            chart = chart_items(245 + taller)
        story.extend([_level_panels(chart, guide, (radar_width, guide_width), paddings=(14, 16)), Spacer(1, 9)])
        if not index and tiles is not None:
            # The tiles are the one optional row: with many competencies the first page is full without them.
            first_page = story + ([_change_legend(width)] if len(groups) == 1 else [])
            if sum(_height(flowable, width) for flowable in first_page) > page_h - 39 - 42 - 14:
                del story[tiles_at:tiles_at + 2]
    story.append(_change_legend(width))
    if prepared:
        story.extend([PageBreak(), _p("역량별 결과와 보완 가이드", size=20, bold=True), Spacer(1, 6),
            _p("역량별 교육 전후 변화와 교육 후 행동 빈도 구간에 따른 안내입니다.", size=9, color=MUTED), Spacer(1, 15)])
        targets = config.get("target_means") or {}
        for index, row in enumerate(prepared, 1):
            story.extend([_competency_card(index, row, width, is_org=is_org, target=_score(targets.get(str(row.get("factor_code"))))),
                          Spacer(1, 10)])
    # The frequency bands explain the wording on the competency cards, so they close that section, not the course list.
    rules = [_p("※ 교육 후 행동 빈도 구간: 높음 4.20 이상 / 비교적 높음 3.40~4.19 / 중간 2.60~3.39 / 낮음 1.80~2.59 / 매우 낮음 1.00~1.79",
                size=7.5, color=MUTED)]
    if prepared:
        story.extend([*rules, Spacer(1, 6)])
    if is_org:
        story.extend(_heatmap_story(heatmap, prepared, width))
    if transfer is not None or courses is not None:
        story.extend(_followup_story(transfer, courses, width))
    if not prepared:
        story.extend([Spacer(1, 4), *rules])

    def page(canvas, document):
        canvas.saveState()
        canvas.setFillColor(colors.HexColor("#f7f8f9"))
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
