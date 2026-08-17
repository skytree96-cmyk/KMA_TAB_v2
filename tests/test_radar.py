import unittest

from tap.radar import (
    build_planning_preview_radar,
    build_pre_post_radar,
    build_pre_post_radar_html,
    prepare_radar_data,
    select_radar_factors,
)


def _row(
    index: int,
    *,
    pre: float = 3.0,
    post: float = 3.5,
    change: float = 0.5,
    paired_n: int = 7,
    status: str = "공개",
) -> dict[str, object]:
    return {
        "factor_code": f"F{index}",
        "factor_name_ko": f"역량 {index}",
        "pre_mean": pre,
        "post_mean": post,
        "change": change,
        "paired_n": paired_n,
        "status": status,
    }


class RadarTests(unittest.TestCase):
    def test_more_than_eight_uses_fixed_preferred_order_then_korean_name(self) -> None:
        rows = [_row(index, change=index / 10) for index in range(1, 11)]

        selected = select_radar_factors(rows, preferred_codes=["F1", "F9", "F3"])

        self.assertEqual(8, len(selected))
        # Preferred codes stay fixed; change magnitude does not reorder axes.
        self.assertEqual(
            ["역량 1", "역량 9", "역량 3", "역량 10", "역량 2", "역량 4", "역량 5", "역량 6"],
            [row["factor_name_ko"] for row in selected],
        )

    def test_metadata_reports_selected_and_omitted_counts(self) -> None:
        prepared = prepare_radar_data([_row(index) for index in range(1, 11)])

        self.assertEqual(8, prepared["selected_count"])
        self.assertEqual(2, prepared["omitted_count"])
        self.assertEqual(10, prepared["eligible_count"])
        self.assertEqual(8, prepared["axis_count"])
        self.assertEqual(8, prepared["max_axes"])

        artifact = build_pre_post_radar([_row(index) for index in range(1, 11)])
        self.assertEqual(8, artifact["selected_count"])
        self.assertEqual(2, artifact["omitted_count"])
        self.assertIn("<svg", artifact["html"])

    def test_private_or_missing_rows_are_removed_before_rendering(self) -> None:
        rows = [
            _row(1, pre=1.17, post=4.91, change=3.74, paired_n=4, status="비공개(N<5)"),
            _row(2, pre=2.22, post=4.44, change=2.22, paired_n=9, status="private"),
            _row(3, pre=3.33, post=4.33, change=1.0, paired_n=9),
            {**_row(4), "post_mean": None},
            _row(5),
            _row(6),
        ]

        html = build_pre_post_radar_html(rows)

        self.assertEqual(["역량 3", "역량 5", "역량 6"], [row["factor_name_ko"] for row in select_radar_factors(rows)])
        self.assertNotIn("1.17", html)
        self.assertNotIn("4.91", html)
        self.assertNotIn("3.74", html)
        self.assertNotIn("2.22", html)
        self.assertNotIn("역량 1", html)
        self.assertNotIn("역량 2", html)
        self.assertNotIn("역량 4", html)

    def test_eight_public_factors_render_an_eight_axis_svg_and_table(self) -> None:
        html = build_pre_post_radar_html([_row(index) for index in range(1, 9)])

        self.assertIn('data-axis-count="8"', html)
        self.assertIn('data-selected-count="8"', html)
        self.assertIn('data-omitted-count="0"', html)
        self.assertIn("<svg", html)
        self.assertIn('role="img"', html)
        self.assertIn("교육 전", html)
        self.assertIn("교육 후", html)
        self.assertIn("척도 1~5", html)
        self.assertIn("짝지어진 N", html)
        self.assertEqual(8, html.count('<th scope="row">'))

    def test_fewer_than_eight_uses_actual_axis_count_without_fake_data(self) -> None:
        html = build_pre_post_radar_html([_row(index) for index in range(1, 6)])

        self.assertIn('data-axis-count="5"', html)
        self.assertIn("공개 가능한 5개 역량을 실제 축으로 표시했습니다", html)
        self.assertIn("가상 축은 추가하지 않았습니다", html)
        self.assertNotIn("역량 6", html)

    def test_one_or_two_public_factors_show_message_instead_of_svg(self) -> None:
        html = build_pre_post_radar_html([_row(1), _row(2)])

        self.assertIn('data-axis-count="2"', html)
        self.assertNotIn("<svg", html)
        self.assertIn("최소 3개 필요", html)
        self.assertIn("가짜 축은 추가하지 않았습니다", html)
        # Public values remain available in the accessible fallback table.
        self.assertEqual(2, html.count('<th scope="row">'))

    def test_nonfinite_and_out_of_range_values_are_suppressed(self) -> None:
        rows = [
            _row(1, pre=float("nan")),
            _row(2, post=6.0),
            _row(3, change=5.0),
            _row(4, paired_n=5),
        ]

        self.assertEqual(["역량 4"], [row["factor_name_ko"] for row in select_radar_factors(rows)])

    def test_html_escapes_title_and_factor_names(self) -> None:
        row = _row(1)
        row["factor_name_ko"] = '<img src=x onerror="alert(1)">'

        html = build_pre_post_radar_html([row, _row(2), _row(3)], title="<script>x</script>")

        self.assertNotIn("<script>x</script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;x&lt;/script&gt;", html)
        self.assertIn("&lt;img", html)

    def test_minimum_paired_n_is_configurable_and_validated(self) -> None:
        self.assertEqual([], select_radar_factors([_row(1, paired_n=5)], min_paired_n=6))
        with self.assertRaises(ValueError):
            select_radar_factors([_row(1)], min_paired_n=0)
        with self.assertRaises(ValueError):
            select_radar_factors([_row(1)], max_axes=9)

    def test_planning_preview_renders_small_n_values_with_visible_print_safe_watermark(self) -> None:
        rows = [
            {
                **_row(index, pre=1.25 + index / 10, post=4.25 + index / 10, paired_n=1),
                "participant_id": "PARTICIPANT-SECRET",
            }
            for index in range(1, 4)
        ]

        artifact = build_planning_preview_radar(
            rows,
            paired_n=1,
            preferred_codes=["F3", "F1", "F2"],
        )
        html = artifact["html"]

        self.assertTrue(artifact["preview_mode"])
        self.assertEqual(1, artifact["paired_n"])
        self.assertEqual(3, artifact["axis_count"])
        self.assertIn('data-preview-mode="true"', html)
        self.assertIn('data-axis-count="3"', html)
        self.assertIn("1.35", html)
        self.assertIn("4.55", html)
        self.assertGreaterEqual(
            html.count("기획검증용 · 소표본 N=1 · 외부 공유 금지"),
            2,
        )
        self.assertIn("@media print", html)
        self.assertIn("display:none!important", html)
        self.assertNotIn("PARTICIPANT-SECRET", html)

    def test_normal_radar_still_suppresses_small_n_values_by_default(self) -> None:
        rows = [_row(index, pre=1.17, post=4.91, paired_n=1) for index in range(1, 4)]

        artifact = build_pre_post_radar(rows)

        self.assertEqual(0, artifact["axis_count"])
        self.assertIn('data-axis-count="0"', artifact["html"])
        self.assertNotIn("1.17", artifact["html"])
        self.assertNotIn("4.91", artifact["html"])
        self.assertNotIn("<svg", artifact["html"])

    def test_planning_preview_escapes_title_and_factor_names(self) -> None:
        rows = [_row(index, paired_n=1) for index in range(1, 4)]
        rows[0]["factor_name_ko"] = '<img src=x onerror="alert(1)">'

        html = build_planning_preview_radar(
            rows,
            paired_n=1,
            title="<script>alert(1)</script>",
        )["html"]

        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;img", html)


if __name__ == "__main__":
    unittest.main()
