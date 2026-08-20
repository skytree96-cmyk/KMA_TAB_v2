from __future__ import annotations

"""Shared company-scope gate for company-manager Streamlit pages.

The gate follows the role-separated LXP pattern: a company administrator must
first establish one organization context, and every project/report page then
operates inside that context. Raw business-registration numbers and raw access
codes live only in disposable page widget keys.
"""

from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping

from tap.github_demo_store import DemoStoreConfig, DemoStoreError, GitHubDemoStore
from tap.runtime_guard import source_fingerprint
from tap.state import COMPANY_SCOPE_VERIFIED_KEY, activate_company_scope
from tap.tenant import (
    CompanyIdentity,
    TenantError,
    access_codes_equal,
    derive_company_identity,
    hash_company_access_code,
    normalize_access_code,
    validate_access_code,
    verify_company_access_code,
)


__tap_source_sha256__ = source_fingerprint(__file__)


IDENTITY_OPTIONS = {
    "kma": "KMA 부여 기업코드",
    "business": "회사명 + 사업자등록번호",
}


@dataclass(frozen=True)
class CompanyScopeView:
    verified: bool
    company_id: str = ""
    company_name: str = ""
    identity_source: str = ""
    access_digest: str = ""
    # A raw code is returned only from this page's disposable password widget.
    # It is never copied into canonical state or a persisted payload.
    access_code: str = field(default="", repr=False)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _widget_key(prefix: str, suffix: str) -> str:
    return f"_{prefix}_company_scope_{suffix}"


def _scope_from_state(
    state: Mapping[str, Any], *, access_code: str = ""
) -> CompanyScopeView:
    return CompanyScopeView(
        verified=bool(state.get(COMPANY_SCOPE_VERIFIED_KEY)),
        company_id=_clean(state.get("company_id")),
        company_name=_clean(state.get("company_name")),
        identity_source=_clean(state.get("company_identity_source")),
        access_digest=_clean(state.get("company_access_digest")),
        access_code=normalize_access_code(access_code),
    )


def _registry_identity(
    fallback: CompanyIdentity, registry: Mapping[str, Any]
) -> CompanyIdentity:
    return CompanyIdentity(
        company_id=_clean(registry.get("company_id")) or fallback.company_id,
        company_name=_clean(registry.get("company_name")) or fallback.company_name,
        identity_source=(
            _clean(registry.get("company_identity_source"))
            or _clean(registry.get("identity_source"))
            or fallback.identity_source
        ),
    )


def render_company_scope_gate(
    st: Any,
    config: DemoStoreConfig,
    *,
    key_prefix: str,
    heading: str = "기업 범위 확인",
) -> CompanyScopeView:
    """Render and verify one company-admin context.

    Registry metadata may be read internally before verification, but project
    lists and completion data are intentionally left to callers and must not be
    queried until this function returns ``verified=True``.
    """

    state: MutableMapping[str, Any] = st.session_state
    mode_key = _widget_key(key_prefix, "identity_mode")
    name_key = _widget_key(key_prefix, "company_name")
    kma_key = _widget_key(key_prefix, "kma_code")
    business_key = _widget_key(key_prefix, "business_number")
    admin_key = _widget_key(key_prefix, "admin_code")
    bootstrap_key = _widget_key(key_prefix, "bootstrap_code")

    current = _scope_from_state(state, access_code=state.get(admin_key, ""))
    if current.verified and current.company_id:
        display_name = current.company_name or "등록 기업"
        st.success(
            f"현재 회사 범위 · {display_name} · 기업 ID {current.company_id[:12]}…"
        )
        panel = st.expander("회사 범위 변경", expanded=False)
    else:
        panel = st.container(border=True)

    with panel:
        st.markdown(f"#### {heading}")
        st.caption(
            "관리자 화면은 확인된 한 회사의 프로젝트만 보여줍니다. "
            "KMA가 부여한 기업코드가 있으면 우선 사용하세요."
        )
        mode = st.radio(
            "기업 구분 방식",
            options=list(IDENTITY_OPTIONS),
            format_func=IDENTITY_OPTIONS.get,
            horizontal=True,
            key=mode_key,
        )
        company_name = st.text_input(
            "회사명",
            key=name_key,
            placeholder="예: 한국능률협회",
            help="관리자 화면에 표시할 회사명입니다.",
        )
        if mode == "kma":
            kma_assigned_code = st.text_input(
                "KMA 부여 기업코드",
                key=kma_key,
                placeholder="예: KMAA001",
                help="KMA가 회사별로 부여한 코드입니다. 프로젝트 접속코드와 다릅니다.",
            )
            business_registration_number = ""
        else:
            business_registration_number = st.text_input(
                "사업자등록번호",
                key=business_key,
                placeholder="숫자 10자리",
                help="기업 ID 생성에만 사용하며 원문은 GitHub·프로젝트·리포트에 저장하지 않습니다.",
            )
            kma_assigned_code = ""
        admin_code = st.text_input(
            "기업 관리자 확인코드",
            type="password",
            key=admin_key,
            help=(
                "회사별로 다르게 정하는 관리자 코드입니다. 참여자 접속코드·KMA 승인코드와 "
                "별도이며 원문은 저장하지 않습니다."
            ),
        )
        bootstrap_code = st.text_input(
            "KMA 신규기업 등록 승인코드",
            type="password",
            key=bootstrap_key,
            help=(
                "아직 등록되지 않은 회사의 첫 프로젝트에서만 KMA가 전달한 승인코드를 입력합니다. "
                "기존 회사는 비워 두세요."
            ),
        )
        st.caption(
            "사업자등록번호·기업 관리자 확인코드·KMA 등록 승인코드의 원문은 저장하지 않고, "
            "일방향 가명키·검증값만 저장합니다."
        )
        confirm = st.button(
            "기업 범위 확인",
            type="primary",
            width="stretch",
            key=_widget_key(key_prefix, "confirm"),
        )

    if not confirm:
        return _scope_from_state(state, access_code=state.get(admin_key, ""))

    try:
        if not config.salt:
            raise TenantError(
                "기업 가명키 생성용 salt가 설정되지 않아 기업을 확인할 수 없습니다."
            )
        identity = derive_company_identity(
            salt=config.salt,
            company_name=company_name,
            business_registration_number=business_registration_number,
            kma_assigned_code=kma_assigned_code,
        )
        if not _clean(identity.company_name):
            raise TenantError("관리자 화면에 표시할 회사명을 입력해 주세요.")
        normalized_admin_code = validate_access_code(
            admin_code,
            "기업 관리자 확인코드",
        )
        if config.participant_code and access_codes_equal(
            normalized_admin_code,
            config.participant_code,
        ):
            raise TenantError(
                "기업 관리자 확인코드는 참여자 접속코드와 다르게 설정해 주세요."
            )

        registry: Mapping[str, Any] | None = None
        if config.read_enabled:
            registry = GitHubDemoStore(config).load_company(identity.company_id)

        if registry is not None:
            digest = _clean(registry.get("company_access_digest"))
            if not verify_company_access_code(
                identity.company_id,
                normalized_admin_code,
                digest,
                config.salt,
            ):
                raise TenantError("기업 관리자 확인코드가 일치하지 않습니다.")
            identity = _registry_identity(identity, registry)
        else:
            # First project creation is the MVP registration event. The KMA
            # bootstrap approval and the tenant's durable administrator code
            # are deliberately separate so one company's code cannot open
            # another company created with the same bootstrap approval.
            normalized_bootstrap_code = validate_access_code(
                bootstrap_code,
                "KMA 신규기업 등록 승인코드",
            )
            if not config.company_access_granted(normalized_bootstrap_code):
                raise TenantError(
                    "등록된 기업을 찾지 못했습니다. 신규 기업은 KMA가 전달한 "
                    "신규기업 등록 승인코드가 필요합니다."
                )
            if access_codes_equal(
                normalized_bootstrap_code,
                normalized_admin_code,
            ):
                raise TenantError(
                    "KMA 등록 승인코드와 기업 관리자 확인코드는 서로 다르게 설정해 주세요."
                )
            digest = hash_company_access_code(
                identity.company_id,
                normalized_admin_code,
                config.salt,
            )

        activate_company_scope(
            state,
            company_id=identity.company_id,
            company_name=identity.company_name,
            identity_source=identity.identity_source,
            access_digest=digest,
        )
        st.rerun()
    except (TenantError, DemoStoreError) as exc:
        st.error(str(exc))

    return _scope_from_state(state, access_code=state.get(admin_key, ""))


def company_admin_code_from_page(state: Mapping[str, Any], key_prefix: str) -> str:
    """Return this page's disposable company-admin code, if still present."""

    return normalize_access_code(state.get(_widget_key(key_prefix, "admin_code")))


def company_registration_code_from_page(
    state: Mapping[str, Any], key_prefix: str
) -> str:
    """Return the disposable KMA new-company registration approval code."""

    return normalize_access_code(
        state.get(_widget_key(key_prefix, "bootstrap_code"))
    )


__all__ = [
    "CompanyScopeView",
    "company_admin_code_from_page",
    "company_registration_code_from_page",
    "render_company_scope_gate",
]
