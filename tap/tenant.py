from __future__ import annotations

"""Privacy-preserving tenant identity helpers for the TAP planning demo.

The public demo needs a stable organization boundary without putting a Korean
business registration number or an access code in GitHub.  This module keeps
those values as one-way HMAC inputs only.  It intentionally does not attempt
to replace production tenant registration, identity proofing, or RBAC.
"""

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from tap.runtime_guard import source_fingerprint


__tap_source_sha256__ = source_fingerprint(__file__)


_COMPANY_ID_RE = re.compile(r"^org_[0-9a-f]{64}$")
_BUSINESS_NUMBER_RE = re.compile(r"^[0-9]{10}$")
_KMA_CODE_RE = re.compile(r"^[A-Z0-9]{4,64}$")
_ACCESS_DIGEST_RE = {
    "company": re.compile(r"^cac_[0-9a-f]{64}$"),
    "participant": re.compile(r"^pac_[0-9a-f]{64}$"),
}


class TenantError(ValueError):
    """Raised when an organization identity or access proof is invalid."""


def _clean(value: Any) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).strip()


def normalize_access_code(value: Any) -> str:
    """Return the canonical representation used by every access-code path.

    NFKC prevents visually equivalent full-width/compatibility characters from
    bypassing role-separation checks.  Callers that need to require a code
    should additionally use :func:`validate_access_code`.
    """

    return _clean(value)


def validate_access_code(
    value: Any,
    label: str = "접속코드",
    *,
    required: bool = True,
) -> str:
    """Normalize and validate one configured or user-supplied access code."""

    cleaned = normalize_access_code(value)
    if not cleaned and not required:
        return ""
    if not 3 <= len(cleaned) <= 128 or any(
        char in cleaned for char in "\r\n\t\x00"
    ):
        raise TenantError(f"{label}는 줄바꿈 없이 3~128자로 입력해 주세요.")
    return cleaned


def access_codes_equal(left: Any, right: Any) -> bool:
    """Compare normalized access codes in constant time without Unicode errors."""

    normalized_left = normalize_access_code(left)
    normalized_right = normalize_access_code(right)
    if not normalized_left or not normalized_right:
        return False
    return hmac.compare_digest(
        normalized_left.encode("utf-8"),
        normalized_right.encode("utf-8"),
    )


def _secret(value: Any, label: str) -> str:
    cleaned = _clean(value)
    if not cleaned:
        raise TenantError(f"{label}에 사용할 비밀 salt가 필요합니다.")
    return cleaned


def _company_name(value: Any, *, required: bool) -> str:
    raw = _clean(value)
    if any(char in raw for char in "\r\n\t\x00"):
        raise TenantError("회사명은 줄바꿈 없이 120자 이하로 입력해 주세요.")
    cleaned = " ".join(raw.split())
    if required and not cleaned:
        raise TenantError("회사명을 입력해 주세요.")
    if len(cleaned) > 120 or any(char in cleaned for char in "\r\n\t\x00"):
        raise TenantError("회사명은 줄바꿈 없이 120자 이하로 입력해 주세요.")
    return cleaned


def _business_number(value: Any) -> str:
    # Hyphens and ordinary spaces are display punctuation, not identity data.
    cleaned = re.sub(r"[-\s]", "", _clean(value))
    if not _BUSINESS_NUMBER_RE.fullmatch(cleaned):
        raise TenantError("사업자등록번호는 숫자 10자리로 입력해 주세요.")
    return cleaned


def normalize_business_registration_number(value: Any) -> str:
    """Return the canonical 10-digit business number used as an HMAC input.

    The value is intentionally returned only to the caller handling the
    disposable form. It must never be copied into canonical state or persisted.
    """

    return _business_number(value)


def _kma_code(value: Any) -> str:
    cleaned = re.sub(r"[-\s]", "", _clean(value)).upper()
    if not _KMA_CODE_RE.fullmatch(cleaned):
        raise TenantError("KMA 기업코드는 영문·숫자 4~64자로 입력해 주세요.")
    return cleaned


def _digest(namespace: str, identity: str, salt: str) -> str:
    return hmac.new(
        _secret(salt, "기업 식별").encode("utf-8"),
        f"tap-tenant-v1\x00{namespace}\x00{identity}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@dataclass(frozen=True)
class CompanyIdentity:
    """Safe organization metadata that may be persisted.

    The raw business registration number and the KMA-issued enrollment code
    are deliberately not fields, so neither ``repr`` nor ``to_payload`` can
    expose them accidentally.
    """

    company_id: str
    company_name: str
    identity_source: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "company_id", validate_company_id(self.company_id))
        object.__setattr__(
            self,
            "company_name",
            _company_name(self.company_name, required=False),
        )
        if self.identity_source not in {"business_registration", "kma_assigned"}:
            raise TenantError("지원하지 않는 기업 식별 방식입니다.")

    def to_payload(self) -> dict[str, str]:
        return {
            "company_id": self.company_id,
            "company_name": self.company_name,
            "company_identity_source": self.identity_source,
        }


def validate_company_id(value: Any) -> str:
    """Return a normalized safe company ID or raise ``TenantError``."""

    cleaned = _clean(value).lower()
    if not _COMPANY_ID_RE.fullmatch(cleaned):
        raise TenantError("company_id 형식이 올바르지 않습니다.")
    return cleaned


def derive_company_identity(
    *,
    salt: str,
    company_name: Any = "",
    business_registration_number: Any = "",
    kma_assigned_code: Any = "",
) -> CompanyIdentity:
    """Derive a stable, non-reversible company identity.

    Exactly one proof source is accepted.  A business-number identity is bound
    only to the normalized number, so spacing, legal-name notation, and later
    display-name changes do not split one company.  A KMA-issued code uses a
    separate namespace.
    """

    has_business = bool(_clean(business_registration_number))
    has_kma_code = bool(_clean(kma_assigned_code))
    if has_business == has_kma_code:
        raise TenantError("사업자등록번호 또는 KMA 기업코드 중 하나만 입력해 주세요.")

    if has_business:
        display_name = _company_name(company_name, required=True)
        registration_number = _business_number(business_registration_number)
        digest = _digest(
            "business-registration",
            registration_number,
            salt,
        )
        source = "business_registration"
    else:
        display_name = _company_name(company_name, required=False)
        digest = _digest("kma-assigned", _kma_code(kma_assigned_code), salt)
        source = "kma_assigned"

    return CompanyIdentity(
        company_id=f"org_{digest}",
        company_name=display_name,
        identity_source=source,
    )


def derive_company_id(**kwargs: Any) -> str:
    """Convenience wrapper returning only the safe ID."""

    return derive_company_identity(**kwargs).company_id


def _access_code(value: Any, label: str) -> str:
    return validate_access_code(value, label)


def _access_digest(
    namespace: str,
    company_id: Any,
    access_code: Any,
    salt: Any,
    *,
    project_id: Any = "",
) -> str:
    company = validate_company_id(company_id)
    label = "기업 관리자 접속코드" if namespace == "company" else "참여자 접속코드"
    candidate = _access_code(access_code, label)
    scope = _clean(project_id) if namespace == "participant" else ""
    digest = hmac.new(
        _secret(salt, "접속코드 검증").encode("utf-8"),
        f"tap-access-v1\x00{namespace}\x00{company}\x00{scope}\x00{candidate}".encode(
            "utf-8"
        ),
        hashlib.sha256,
    ).hexdigest()
    prefix = "cac" if namespace == "company" else "pac"
    return f"{prefix}_{digest}"


def hash_company_access_code(company_id: Any, access_code: Any, salt: Any) -> str:
    """Create a persistable proof for a company administrator code."""

    return _access_digest("company", company_id, access_code, salt)


def verify_company_access_code(
    company_id: Any,
    candidate: Any,
    stored_digest: Any,
    salt: Any,
) -> bool:
    """Constant-time verification in the company-admin namespace."""

    expected = _clean(stored_digest).lower()
    if not _ACCESS_DIGEST_RE["company"].fullmatch(expected):
        return False
    try:
        actual = hash_company_access_code(company_id, candidate, salt)
    except TenantError:
        return False
    return hmac.compare_digest(expected, actual)


def hash_participant_access_code(
    company_id: Any,
    access_code: Any,
    salt: Any,
    *,
    project_id: Any = "",
) -> str:
    """Create a participant-code proof in a separate cryptographic namespace."""

    return _access_digest(
        "participant",
        company_id,
        access_code,
        salt,
        project_id=project_id,
    )


def verify_participant_access_code(
    company_id: Any,
    candidate: Any,
    stored_digest: Any,
    salt: Any,
    *,
    project_id: Any = "",
) -> bool:
    """Constant-time verification in the participant namespace."""

    expected = _clean(stored_digest).lower()
    if not _ACCESS_DIGEST_RE["participant"].fullmatch(expected):
        return False
    try:
        actual = hash_participant_access_code(
            company_id,
            candidate,
            salt,
            project_id=project_id,
        )
    except TenantError:
        return False
    return hmac.compare_digest(expected, actual)


__all__ = [
    "CompanyIdentity",
    "TenantError",
    "access_codes_equal",
    "derive_company_id",
    "derive_company_identity",
    "hash_company_access_code",
    "hash_participant_access_code",
    "normalize_access_code",
    "normalize_business_registration_number",
    "validate_company_id",
    "validate_access_code",
    "verify_company_access_code",
    "verify_participant_access_code",
]
