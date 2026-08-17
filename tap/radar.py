from __future__ import annotations

import hashlib
import math
from html import escape
from typing import Any, Iterable, Mapping

from tap.runtime_guard import source_fingerprint


__tap_source_sha256__ = source_fingerprint(__file__)


MIN_RADAR_AXES = 3
MAX_RADAR_AXES = 8
DEFAULT_MIN_PAIRED_N = 5

_PRIVATE_STATUS_MARKERS = (
    "비공개",
    "미공개",
    "공개 불가",
    "소표본",
    "private",
    "restricted",
    "confidential",
    "suppressed",
    "masked",
    "보호",
)


def _finite_number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _paired_count(value: Any) -> int | None:
    number = _finite_number(value)
    if number is None or number < 0 or not number.is_integer():
        return None
    return int(number)


def _is_private_status(value: Any) -> bool:
    status = str(value or "").strip().lower()
    return any(marker in status for marker in _PRIVATE_STATUS_MARKERS)


def _normalise_public_factor(
    row: Mapping[str, Any],
    *,
    source_index: int,
    min_paired_n: int,
) -> dict[str, Any] | None:
    """Return a public, chart-safe factor or ``None``.

    A factor is suppressed as a whole when its status is private, paired N is
    below the threshold, or any chart number is missing/invalid. Raw private
    values are never retained in the returned object, which keeps downstream
    HTML and accessibility output from leaking them accidentally.
    """
    if _is_private_status(row.get("status")):
        return None

    paired_n = _paired_count(row.get("paired_n"))
    pre_mean = _finite_number(row.get("pre_mean"))
    post_mean = _finite_number(row.get("post_mean"))
    change = _finite_number(row.get("change", row.get("observed_change")))
    if (
        paired_n is None
        or paired_n < min_paired_n
        or pre_mean is None
        or post_mean is None
        or change is None
        or not 1.0 <= pre_mean <= 5.0
        or not 1.0 <= post_mean <= 5.0
        or not -4.0 <= change <= 4.0
    ):
        return None

    name = str(row.get("factor_name_ko") or "").strip()
    if not name:
        return None
    return {
        "factor_code": str(row.get("factor_code") or "").strip(),
        "factor_name_ko": name,
        "pre_mean": pre_mean,
        "post_mean": post_mean,
        "change": change,
        "paired_n": paired_n,
        "_source_index": source_index,
    }


def select_radar_factors(
    rows: Iterable[Mapping[str, Any]],
    *,
    min_paired_n: int = DEFAULT_MIN_PAIRED_N,
    preferred_codes: Iterable[str] = (),
    max_axes: int = MAX_RADAR_AXES,
) -> list[dict[str, Any]]:
    """Select at most eight public factors for the pre/post radar.

    Selection is deterministic and does not depend on result size or change:
    factors present in ``preferred_codes`` are placed in that exact order, then
    all remaining factors are ordered by Korean name (and code as a tie-break).
    A caller can therefore pass ``organization_priorities + selected_factors``
    to keep the same representative axes across reporting waves.

    If fewer than eight factors are public, every public factor is returned;
    no placeholder or synthetic axis is created.
    """
    if min_paired_n < 1:
        raise ValueError("min_paired_n must be at least 1")
    if not 1 <= max_axes <= MAX_RADAR_AXES:
        raise ValueError(f"max_axes must be between 1 and {MAX_RADAR_AXES}")

    public: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        normalised = _normalise_public_factor(
            row,
            source_index=index,
            min_paired_n=min_paired_n,
        )
        if normalised is not None:
            public.append(normalised)

    preferred_order: dict[str, int] = {}
    for code in preferred_codes:
        clean_code = str(code or "").strip()
        if clean_code and clean_code not in preferred_order:
            preferred_order[clean_code] = len(preferred_order)
    selected = sorted(
        public,
        key=lambda row: (
            0 if str(row["factor_code"]) in preferred_order else 1,
            preferred_order.get(str(row["factor_code"]), len(preferred_order)),
            str(row["factor_name_ko"]),
            str(row["factor_code"]),
        ),
    )[:max_axes]
    return [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in selected
    ]


def prepare_radar_data(
    rows: Iterable[Mapping[str, Any]],
    *,
    min_paired_n: int = DEFAULT_MIN_PAIRED_N,
    preferred_codes: Iterable[str] = (),
    max_axes: int = MAX_RADAR_AXES,
) -> dict[str, Any]:
    """Return selected public factors plus non-sensitive chart metadata."""
    source_rows = list(rows)
    eligible_count = sum(
        _normalise_public_factor(row, source_index=index, min_paired_n=min_paired_n)
        is not None
        for index, row in enumerate(source_rows)
    )
    factors = select_radar_factors(
        source_rows,
        min_paired_n=min_paired_n,
        preferred_codes=preferred_codes,
        max_axes=max_axes,
    )
    selected_count = len(factors)
    return {
        "factors": factors,
        "selected_count": selected_count,
        "eligible_count": eligible_count,
        "omitted_count": max(0, eligible_count - selected_count),
        "excluded_count": max(0, len(source_rows) - eligible_count),
        "axis_count": selected_count if selected_count >= MIN_RADAR_AXES else 0,
        "max_axes": max_axes,
    }


def _point(cx: float, cy: float, radius: float, angle: float) -> tuple[float, float]:
    return cx + radius * math.cos(angle), cy + radius * math.sin(angle)


def _points(values: Iterable[float], *, cx: float, cy: float, radius: float) -> str:
    scores = list(values)
    count = len(scores)
    coordinates = []
    for index, score in enumerate(scores):
        angle = -math.pi / 2 + (2 * math.pi * index / count)
        x, y = _point(cx, cy, radius * score / 5.0, angle)
        coordinates.append(f"{x:.1f},{y:.1f}")
    return " ".join(coordinates)


def _grid_points(count: int, level: int, *, cx: float, cy: float, radius: float) -> str:
    return _points([float(level)] * count, cx=cx, cy=cy, radius=radius)


def _wrapped_label(name: str, limit: int = 9) -> tuple[str, ...]:
    """Fit a Korean label into at most two short SVG lines."""
    if len(name) <= limit:
        return (name,)
    if " " in name:
        words = name.split()
        first = ""
        rest: list[str] = []
        for word in words:
            candidate = f"{first} {word}".strip()
            if not rest and len(candidate) <= limit:
                first = candidate
            else:
                rest.append(word)
        second = " ".join(rest)
    else:
        first, second = name[:limit], name[limit:]
    if len(second) > limit:
        second = second[: max(1, limit - 1)] + "…"
    return tuple(value for value in (first, second) if value)


def _format_change(value: float) -> str:
    clean = 0.0 if abs(value) < 0.005 else value
    return f"{clean:+.2f}"


def _accessible_table(factors: list[dict[str, Any]], chart_id: str) -> str:
    rows = "".join(
        "<tr>"
        f"<th scope=\"row\">{escape(str(row['factor_name_ko']))}</th>"
        f"<td>{float(row['pre_mean']):.2f}</td>"
        f"<td>{float(row['post_mean']):.2f}</td>"
        f"<td>{_format_change(float(row['change']))}</td>"
        f"<td>{int(row['paired_n'])}</td>"
        "</tr>"
        for row in factors
    )
    return f"""
      <div class="tap-radar-table-wrap" tabindex="0" aria-label="교육 전후 역량 비교 상세표">
        <table class="tap-radar-table">
          <caption id="{chart_id}-table-caption">차트에 표시된 역량의 교육 전후 상세 수치</caption>
          <thead><tr><th scope="col">역량</th><th scope="col">교육 전</th><th scope="col">교육 후</th><th scope="col">변화</th><th scope="col">짝지어진 N</th></tr></thead>
          <tbody>{rows}</tbody>
        </table>
      </div>
    """


def build_pre_post_radar_html(
    rows: Iterable[Mapping[str, Any]],
    *,
    title: str = "교육 전후 역량 비교",
    min_paired_n: int = DEFAULT_MIN_PAIRED_N,
    preferred_codes: Iterable[str] = (),
    max_axes: int = MAX_RADAR_AXES,
) -> str:
    """Build a self-contained, Streamlit-safe pre/post radar HTML fragment.

    Render with ``st.html(...)`` (Streamlit 1.31+) or
    ``st.markdown(..., unsafe_allow_html=True)``. No JavaScript or third-party
    chart library is required.
    """
    prepared = prepare_radar_data(
        rows,
        min_paired_n=min_paired_n,
        preferred_codes=preferred_codes,
        max_axes=max_axes,
    )
    factors = list(prepared["factors"])
    omitted_count = int(prepared["omitted_count"])
    chart_key = "|".join(
        [title]
        + [
            f"{row['factor_name_ko']}:{row['pre_mean']}:{row['post_mean']}"
            for row in factors
        ]
    )
    chart_id = "tap-radar-" + hashlib.sha1(chart_key.encode("utf-8")).hexdigest()[:10]
    safe_title = escape(str(title))

    selection_note = (
        f"최대 {max_axes}개 역량 표시 · 대표 역량 선정: 프로젝트 고정 우선순서 → 나머지 역량명 가나다순."
        if omitted_count
        else (
            f"최대 {max_axes}개 역량 표시 · 공개 가능한 {len(factors)}개 역량을 실제 축으로 표시했습니다. 가상 축은 추가하지 않았습니다."
            if len(factors) < max_axes
            else f"최대 {max_axes}개 역량 표시 · 프로젝트 고정 우선순서와 역량명 순서로 표시했습니다."
        )
    )

    styles = """
      <style>
        .tap-radar{color-scheme:light;background:#fff;border:1px solid #d7e4e3;border-radius:20px;padding:22px;color:#143638;font-family:Pretendard,"Noto Sans KR","Malgun Gothic",sans-serif;box-sizing:border-box}
        .tap-radar *{box-sizing:border-box}.tap-radar h3{margin:0;font-size:22px;line-height:1.35;color:#123436}.tap-radar-note{margin:7px 0 14px;color:#587173;font-size:13px;line-height:1.55}
        .tap-radar-legend{display:flex;gap:18px;align-items:center;flex-wrap:wrap;margin:0 0 8px;font-size:14px;font-weight:700}.tap-radar-key{display:inline-flex;gap:7px;align-items:center}.tap-radar-swatch{width:22px;height:4px;border-radius:99px}.tap-radar-pre{background:#2563eb}.tap-radar-post{background:#0f9d8a}
        .tap-radar svg{display:block;width:100%;height:auto;max-height:620px}.tap-radar-message{padding:28px 18px;border-radius:14px;background:#f3f8f7;color:#35585a;text-align:center;line-height:1.6}
        .tap-radar-table-wrap{overflow-x:auto;margin-top:14px;border:1px solid #d7e4e3;border-radius:12px}.tap-radar-table{border-collapse:collapse;width:100%;min-width:560px;font-size:13px}.tap-radar-table caption{padding:10px 12px;text-align:left;font-weight:750;color:#35585a;background:#f5f9f8}.tap-radar-table th,.tap-radar-table td{padding:9px 12px;border-top:1px solid #e3eceb;text-align:right;white-space:nowrap}.tap-radar-table th:first-child{text-align:left}.tap-radar-table thead th{background:#f8fbfa;color:#3e5c5e}.tap-radar-table tbody th{color:#173b3d}
        @media(max-width:640px){.tap-radar{padding:16px}.tap-radar h3{font-size:19px}.tap-radar svg{min-width:610px}.tap-radar-chart-scroll{overflow-x:auto}}
      </style>
    """
    table = _accessible_table(factors, chart_id) if factors else ""
    if len(factors) < MIN_RADAR_AXES:
        message = (
            f"레이더 그래프에는 공개 가능한 역량이 최소 {MIN_RADAR_AXES}개 필요합니다. "
            f"현재 공개 가능한 역량은 {len(factors)}개이며, 가짜 축은 추가하지 않았습니다."
        )
        return f"""
        <section class="tap-radar" id="{chart_id}" aria-labelledby="{chart_id}-heading" data-axis-count="{len(factors)}" data-selected-count="{prepared['selected_count']}" data-omitted-count="{prepared['omitted_count']}">
          {styles}<h3 id="{chart_id}-heading">{safe_title}</h3>
          <p class="tap-radar-note">{escape(selection_note)}</p>
          <div class="tap-radar-message" role="status">{escape(message)}</div>{table}
        </section>
        """

    width, height = 760.0, 600.0
    cx, cy, radius = 380.0, 280.0, 185.0
    count = len(factors)
    grid = "".join(
        f'<polygon points="{_grid_points(count, level, cx=cx, cy=cy, radius=radius)}" fill="none" stroke="#dce8e7" stroke-width="1"/>'
        for level in range(1, 6)
    )
    axes: list[str] = []
    labels: list[str] = []
    for index, row in enumerate(factors):
        angle = -math.pi / 2 + (2 * math.pi * index / count)
        axis_x, axis_y = _point(cx, cy, radius, angle)
        axes.append(
            f'<line x1="{cx:.1f}" y1="{cy:.1f}" x2="{axis_x:.1f}" y2="{axis_y:.1f}" stroke="#c5d6d5" stroke-width="1"/>'
        )
        label_x, label_y = _point(cx, cy, radius + 48, angle)
        if label_x < cx - 20:
            anchor = "end"
        elif label_x > cx + 20:
            anchor = "start"
        else:
            anchor = "middle"
        lines = _wrapped_label(str(row["factor_name_ko"]))
        tspans = "".join(
            f'<tspan x="{label_x:.1f}" dy="{0 if line_index == 0 else 17}">{escape(line)}</tspan>'
            for line_index, line in enumerate(lines)
        )
        labels.append(
            f'<text x="{label_x:.1f}" y="{label_y:.1f}" text-anchor="{anchor}" fill="#24494b" font-size="13" font-weight="700">{tspans}</text>'
        )
    pre_points = _points(
        [float(row["pre_mean"]) for row in factors], cx=cx, cy=cy, radius=radius
    )
    post_points = _points(
        [float(row["post_mean"]) for row in factors], cx=cx, cy=cy, radius=radius
    )
    score_labels = "".join(
        f'<text x="{cx + 7:.1f}" y="{cy - radius * level / 5 + 4:.1f}" fill="#789092" font-size="11">{level}</text>'
        for level in range(1, 6)
    )
    desc = (
        f"1점에서 5점 범위의 {count}축 레이더 그래프입니다. "
        "파란색은 교육 전, 청록색은 교육 후 평균이며 상세 수치는 아래 표에 있습니다."
    )
    svg = f"""
      <div class="tap-radar-chart-scroll">
        <svg viewBox="0 0 {width:.0f} {height:.0f}" role="img" aria-labelledby="{chart_id}-svg-title {chart_id}-svg-desc">
          <title id="{chart_id}-svg-title">{safe_title}</title>
          <desc id="{chart_id}-svg-desc">{escape(desc)}</desc>
          {grid}{''.join(axes)}{score_labels}
          <polygon points="{pre_points}" fill="#2563eb" fill-opacity="0.13" stroke="#2563eb" stroke-width="3" stroke-linejoin="round"/>
          <polygon points="{post_points}" fill="#0f9d8a" fill-opacity="0.20" stroke="#0f9d8a" stroke-width="3" stroke-linejoin="round"/>
          {''.join(labels)}
        </svg>
      </div>
    """
    return f"""
    <section class="tap-radar" id="{chart_id}" aria-labelledby="{chart_id}-heading" data-axis-count="{count}" data-selected-count="{prepared['selected_count']}" data-omitted-count="{prepared['omitted_count']}">
      {styles}<h3 id="{chart_id}-heading">{safe_title}</h3>
      <p class="tap-radar-note">{escape(selection_note)}</p>
      <div class="tap-radar-legend" aria-label="범례">
        <span class="tap-radar-key"><span class="tap-radar-swatch tap-radar-pre"></span>교육 전</span>
        <span class="tap-radar-key"><span class="tap-radar-swatch tap-radar-post"></span>교육 후</span>
        <span>척도 1~5</span>
      </div>
      {svg}{table}
    </section>
    """


def render_pre_post_radar(
    rows: Iterable[Mapping[str, Any]],
    *,
    title: str = "교육 전후 역량 비교",
    min_paired_n: int = DEFAULT_MIN_PAIRED_N,
    preferred_codes: Iterable[str] = (),
    max_axes: int = MAX_RADAR_AXES,
) -> str:
    """Semantic alias used by Streamlit report pages."""
    return build_pre_post_radar_html(
        rows,
        title=title,
        min_paired_n=min_paired_n,
        preferred_codes=preferred_codes,
        max_axes=max_axes,
    )


def build_pre_post_radar(
    rows: Iterable[Mapping[str, Any]],
    *,
    title: str = "교육 전후 역량 비교",
    min_paired_n: int = DEFAULT_MIN_PAIRED_N,
    preferred_codes: Iterable[str] = (),
    max_axes: int = MAX_RADAR_AXES,
) -> dict[str, Any]:
    """Return printable inline HTML together with selection metadata.

    The returned ``html`` contains only inline CSS/SVG and a semantic table, so
    the same fragment can be used by ``st.html`` and a printable report body.
    """
    source_rows = list(rows)
    preferred = list(preferred_codes)
    prepared = prepare_radar_data(
        source_rows,
        min_paired_n=min_paired_n,
        preferred_codes=preferred,
        max_axes=max_axes,
    )
    return {
        **prepared,
        "html": build_pre_post_radar_html(
            source_rows,
            title=title,
            min_paired_n=min_paired_n,
            preferred_codes=preferred,
            max_axes=max_axes,
        ),
    }


__all__ = [
    "DEFAULT_MIN_PAIRED_N",
    "MAX_RADAR_AXES",
    "MIN_RADAR_AXES",
    "build_pre_post_radar",
    "build_pre_post_radar_html",
    "prepare_radar_data",
    "render_pre_post_radar",
    "select_radar_factors",
]
