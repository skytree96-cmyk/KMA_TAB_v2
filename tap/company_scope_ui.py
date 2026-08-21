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
from tap.github_demo_store import company_approval_status
from tap.runtime_guard import source_fingerprint
from tap.state import COMPANY_SCOPE_VERIFIED_KEY, activate_company_scope
from tap.tenant import (
    CompanyIdentity,
    TenantError,
    derive_company_identity,
    hash_company_access_code,
    normalize_business_registration_number,
    verify_company_access_code,
)


__tap_source_sha256__ = source_fingerprint(__file__)


@dataclass(frozen=True)
class CompanyScopeView:
    verified: bool
    company_id: str = ""
    company_name: str = ""
    identity_source: str = ""
    access_digest: str = ""
    approval_status: str = ""
    # For this synthetic planning demo, the normalized business number is the
    # disposable proof used by the store. It is never copied into canonical
    # state, persisted payloads, URLs, logs, or repr output.
    access_code: str = field(default="", repr=False)


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _widget_key(prefix: str, suffix: str) -> str:
    return f"_{prefix}_company_scope_{suffix}"


def _scope_from_state(
    state: Mapping[str, Any], *, access_code: str = "", approval_status: str = ""
) -> CompanyScopeView:
    return CompanyScopeView(
        verified=bool(state.get(COMPANY_SCOPE_VERIFIED_KEY)),
        company_id=_clean(state.get("company_id")),
        company_name=_clean(state.get("company_name")),
        identity_source=_clean(state.get("company_identity_source")),
        access_digest=_clean(state.get("company_access_digest")),
        approval_status=_clean(approval_status),
        access_code=_clean(access_code),
    )


def _clear_verified_scope(state: MutableMapping[str, Any]) -> None:
    state[COMPANY_SCOPE_VERIFIED_KEY] = False
    state["company_access_digest"] = ""


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
    name_key = _widget_key(key_prefix, "company_name")
    business_key = _widget_key(key_prefix, "business_number")
    business_proof = ""
    try:
        if _clean(state.get(business_key)):
            business_proof = normalize_business_registration_number(
                state.get(business_key)
            )
    except TenantError:
        business_proof = ""

    current = _scope_from_state(state, access_code=business_proof)
    if current.company_name and name_key not in state:
        state[name_key] = current.company_name
    if current.verified and current.company_id and config.read_enabled:
        try:
            current_registry = GitHubDemoStore(config).load_company(current.company_id)
            if current_registry is None or company_approval_status(current_registry) != "approved":
                _clear_verified_scope(state)
                current = _scope_from_state(state)
                st.warning("KMA 승인 상태가 변경되어 회사 범위를 다시 확인해야 합니다.")
        except DemoStoreError as exc:
            _clear_verified_scope(state)
            current = _scope_from_state(state)
            st.error(f"기업 승인 상태를 확인하지 못했습니다: {exc}")

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
            "회사명과 사업자등록번호로 참여를 요청합니다. KMA 승인 전에는 "
            "프로젝트·완료 현황·리포트를 열 수 없습니다."
        )
        company_name = st.text_input(
            "회사명",
            key=name_key,
            placeholder="예: 한국능률협회",
            help="관리자 화면에 표시할 회사명입니다.",
        )
        business_registration_number = st.text_input(
            "사업자등록번호",
            key=business_key,
            placeholder="숫자 10자리",
            help="기업 가명키와 확인값 생성에만 사용하며 원문은 저장하지 않습니다.",
        )
        st.caption(
            "사업자등록번호 원문은 기획검증용 저장소·프로젝트·리포트에 저장하지 않습니다. "
            "현재 흐름은 합성데이터 기획검증용이며 실제 계정 인증을 대신하지 않습니다."
        )
        confirm = st.button(
            "회사 확인·참여 요청",
            type="primary",
            width="stretch",
            key=_widget_key(key_prefix, "confirm"),
        )

    if not confirm:
        return _scope_from_state(state, access_code=business_proof)

    try:
        if not config.salt:
            raise TenantError(
                "기업 가명키 생성용 salt가 설정되지 않아 기업을 확인할 수 없습니다."
            )
        identity = derive_company_identity(
            salt=config.salt,
            company_name=company_name,
            business_registration_number=business_registration_number,
        )
        business_proof = normalize_business_registration_number(
            business_registration_number
        )
        digest = hash_company_access_code(
            identity.company_id,
            business_proof,
            config.salt,
        )

        registry: Mapping[str, Any] | None = None
        if config.read_enabled:
            registry = GitHubDemoStore(config).load_company(identity.company_id)

        if registry is None:
            if not config.project_write_enabled:
                raise TenantError(
                    "기업 참여 요청을 저장할 수 없습니다. KMA 관리자에게 저장소 설정을 확인해 주세요."
                )
            registry = GitHubDemoStore(
                config,
                company_access_code=business_proof,
            ).request_company_registration(identity.to_payload(), digest)
            st.success("기업 참여 요청을 접수했습니다. KMA 승인 후 다시 확인해 주세요.")
            return CompanyScopeView(
                verified=False,
                company_id=identity.company_id,
                company_name=identity.company_name,
                identity_source=identity.identity_source,
                access_digest=digest,
                approval_status="pending",
                access_code=business_proof,
            )

        status = company_approval_status(registry)
        if status == "pending":
            st.info("KMA 승인 대기 중입니다. 승인 후 같은 정보로 다시 확인해 주세요.")
            return CompanyScopeView(
                verified=False,
                company_id=identity.company_id,
                company_name=_clean(registry.get("company_name")) or identity.company_name,
                identity_source=identity.identity_source,
                access_digest=digest,
                approval_status=status,
                access_code=business_proof,
            )
        if status == "rejected":
            note = _clean(registry.get("review_note"))
            message = "KMA 검토에서 참여 요청이 반려되었습니다."
            if note:
                message += f" 사유: {note}"
            st.error(message)
            return CompanyScopeView(
                verified=False,
                company_id=identity.company_id,
                company_name=_clean(registry.get("company_name")) or identity.company_name,
                identity_source=identity.identity_source,
                approval_status=status,
            )

        if registry is not None:
            stored_digest = _clean(registry.get("company_access_digest"))
            if not verify_company_access_code(
                identity.company_id,
                business_proof,
                stored_digest,
                config.salt,
            ):
                raise TenantError(
                    "기존 기업 확인방식과 일치하지 않습니다. KMA 관리자에게 기업 등록 전환을 요청해 주세요."
                )
            identity = _registry_identity(identity, registry)

        activate_company_scope(
            state,
            company_id=identity.company_id,
            company_name=identity.company_name,
            identity_source=identity.identity_source,
            access_digest=stored_digest,
        )
        st.rerun()
    except (TenantError, DemoStoreError) as exc:
        st.error(str(exc))

    return _scope_from_state(state, access_code=business_proof)


def company_business_number_from_page(
    state: Mapping[str, Any], key_prefix: str
) -> str:
    """Return the disposable normalized business-number proof, if present."""

    try:
        return normalize_business_registration_number(
            state.get(_widget_key(key_prefix, "business_number"))
        )
    except TenantError:
        return ""


def company_admin_code_from_page(state: Mapping[str, Any], key_prefix: str) -> str:
    """Backward-compatible alias for the disposable business proof."""

    return company_business_number_from_page(state, key_prefix)


def company_registration_code_from_page(
    state: Mapping[str, Any], key_prefix: str
) -> str:
    """Legacy compatibility helper; company pages no longer accept this code."""

    return ""


__all__ = [
    "CompanyScopeView",
    "company_admin_code_from_page",
    "company_business_number_from_page",
    "company_registration_code_from_page",
    "render_company_scope_gate",
]
