from __future__ import annotations

import os
from pathlib import Path
import re
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tap.account_guide import guide_sections

ROOT = Path(__file__).resolve().parents[1]


def _guide_entry():
    from tap.account_guide import render_account_guide

    render_account_guide()


class AccountGuideTests(unittest.TestCase):
    def test_customer_guide_excludes_kma_administrator_workflows(self):
        text = " ".join(" ".join(blocks) for blocks in guide_sections().values())
        for phrase in ("KMA 관리자", "회원사", "문항은행", "사업자등록번호 등록", "교육담당자 계정 발급", "임시 비밀번호는 kma"):
            self.assertNotIn(phrase, text)

    def test_every_numbered_pin_has_a_matching_instruction(self):
        for tab, blocks in guide_sections().items():
            steps = [block for block in blocks if block.startswith('<section class="tg-step">')]
            self.assertGreaterEqual(len(steps), 5, tab)
            for step in steps:
                mock, callouts = step.split('<ol class="tg-callouts">', 1)
                pins = sorted({int(n) for n in re.findall(r'<span class="tg-pin">(\d+)</span>', mock)})
                items = callouts.count("<li>")
                with self.subTest(tab=tab, title=re.search(r"<h3>(.*?)</h3>", step).group(1)):
                    self.assertEqual(pins, list(range(1, items + 1)))

    def test_signed_in_user_opens_guide_from_profile_and_returns_without_logout(self):
        from tap import account_portal

        class Store:
            def principal(self, token):
                return dict(id="p1", login_id="acme-001", display_name="참여자", role="participant",
                            company_id="c1", must_change_password=False)

        env = {"TAP_APP_MODE": "production", "DATABASE_URL": "postgresql://test.invalid/test"}
        with patch.dict(os.environ, env), patch.object(account_portal, "_configured_store", return_value=Store()), \
                patch("tap.account_assessment_ui.render_participant") as participant:
            app = AppTest.from_file(str(ROOT / "streamlit_app.py"))
            app.session_state[account_portal.TOKEN_KEY] = "opaque-token"
            app.run()
            app.button(key="_tap_account_guide_nav").click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.title[0].value, "이용 안내")
            self.assertEqual(app.session_state[account_portal.TOKEN_KEY], "opaque-token")
            participant.reset_mock()
            app.button(key="tap_guide_back").click().run()
            self.assertFalse(app.exception)
            participant.assert_called_once()

    def test_guide_renders_manager_and_participant_tabs(self):
        app = AppTest.from_function(_guide_entry).run()
        self.assertFalse(app.exception)
        self.assertEqual([tab.label for tab in app.tabs], ["교육담당자", "참여자"])
        self.assertEqual(app.title[0].value, "이용 안내")


if __name__ == "__main__":
    unittest.main()
