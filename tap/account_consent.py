"""Privacy consent a participant gives once, before the first answer is stored.

Two agreements, each shown and checked on its own (개인정보 보호법 제22조): collection and use, and provision
to the member company. The privacy policy (KMA 개인정보 처리방침 제1·3·4·6조) says the same; change both together
and raise PRIVACY_CONSENT_VERSION. Storage in Google Cloud Tokyo is neither asked here nor written in the policy,
by KMA's decision of 2026-11-06; whether 제28조의8 needs it is left to the privacy officer.
"""
from __future__ import annotations

from collections.abc import Mapping
from html import escape
from typing import Any

import streamlit as st

from tap.account_store import PRIVACY_CONSENT_ITEMS, PRIVACY_CONSENT_VERSION

PREFIX = "tap_consent_"
KEPT = "검사 응답과 점수는 교육 후 검사 마감일부터 1년, 계정 정보는 회사의 삭제 요청이나 멤버십 계약 종료 때까지"

CONSENT_SECTIONS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("collect", "개인정보 수집·이용", (
        ("목적", "교육 전후 역량검사 시행, 역량별 점수 산출, 본인 리포트와 보완 학습 과정 안내"),
        ("항목", "성명, 아이디, 소속 회사, 부서·직급·이메일·연락처(교육담당자가 등록한 경우), "
                 "검사 응답(문항 응답, 더 배우고 싶은 역량, 현업 적용 환경과 적용 사례), 역량별 점수, 제출 일시, 동의 일시와 접속 IP"),
        ("보유 기간", KEPT),
    )),
    ("provide_company", "소속 회사 제공", (
        ("받는 곳", "소속 회사(KMA 회원사)의 교육담당자"),
        ("목적", "검사 참여 안내, 교육 효과 확인, 다음 교육 계획"),
        ("항목", "성명, 아이디, 부서, 직급, 검사 진행 상태(응답한 문항 수와 제출 여부). "
                 "점수와 학습 희망은 5명 이상 모인 조직·부서 집계로만 제공하고, 개인 점수와 문항별 응답은 제공하지 않음"),
        ("보유 기간", "회사의 교육 운영에 필요한 기간(회사의 개인정보 처리방침에 따름)"),
    )),
)
REFUSAL = "동의하지 않을 수 있습니다. 다만 두 항목 모두 검사에 꼭 필요해서, 동의하지 않으면 TAP 검사를 할 수 없습니다."
assert tuple(code for code, _, _ in CONSENT_SECTIONS) == PRIVACY_CONSENT_ITEMS


def has_consent(principal: Any) -> bool:
    return isinstance(principal, Mapping) and principal.get("privacy_consent_version") == PRIVACY_CONSENT_VERSION


def consent_html() -> str:
    from tap.account_portal import PRIVACY_POLICY_URL
    boxes = []
    for number, (_, title, rows) in enumerate(CONSENT_SECTIONS, 1):
        cells = "".join(f"<dt>{escape(label)}</dt><dd>{escape(text)}</dd>" for label, text in rows)
        boxes.append(f'<section class="tap-consent__box"><h4><span>필수</span>{number}. {escape(title)}</h4><dl>{cells}</dl></section>')
    return ('<div class="tap-consent"><div class="tap-consent__head"><b>검사 전에 개인정보 처리에 동의해 주세요</b>'
            '<p>처음 한 번만 묻습니다. 두 항목은 따로 동의를 받습니다.</p></div>'
            + "".join(boxes)
            + f'<p class="tap-consent__foot">{escape(REFUSAL)} 자세한 내용은 '
              f'<a href="{PRIVACY_POLICY_URL}" target="_blank" rel="noopener">KMA 개인정보 처리방침</a>에 있습니다.</p></div>')


def render_consent(store: Any, token: str) -> None:
    """The consent form; on agreement it records the consent and reruns into the test."""
    from tap.account_access_log import client_address
    st.html(consent_html())
    checks = [st.checkbox(f"{title}에 동의합니다 (필수)", key=PREFIX + code) for code, title, _ in CONSENT_SECTIONS]
    if st.button("동의하고 검사 시작", type="primary", disabled=not all(checks), key=PREFIX + "agree", width="stretch"):
        try:
            store.record_privacy_consent(token, PRIVACY_CONSENT_VERSION, PRIVACY_CONSENT_ITEMS, client=client_address())
        except Exception:
            st.error("동의를 저장하지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
            return
        st.rerun()
