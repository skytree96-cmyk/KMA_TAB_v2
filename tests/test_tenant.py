from __future__ import annotations

import unittest

from tap.tenant import (
    TenantError,
    access_codes_equal,
    derive_company_identity,
    hash_company_access_code,
    hash_participant_access_code,
    normalize_access_code,
    validate_access_code,
    validate_company_id,
    verify_company_access_code,
    verify_participant_access_code,
)


class TenantIdentityTests(unittest.TestCase):
    def test_business_identity_is_stable_and_company_name_is_display_only(self) -> None:
        first = derive_company_identity(
            salt="tenant-secret",
            company_name="한국 능률 협회",
            business_registration_number="123-45-67890",
        )
        renamed = derive_company_identity(
            salt="tenant-secret",
            company_name="KMA 한국능률협회 주식회사",
            business_registration_number="1234567890",
        )
        self.assertEqual(first.company_id, renamed.company_id)
        self.assertRegex(first.company_id, r"^org_[0-9a-f]{64}$")
        self.assertEqual("KMA 한국능률협회 주식회사", renamed.company_name)
        self.assertEqual("business_registration", first.identity_source)
        self.assertNotIn("1234567890", repr(first))
        self.assertNotIn("1234567890", str(first.to_payload()))
        self.assertEqual(first.company_id, validate_company_id(first.company_id.upper()))

    def test_kma_assigned_identity_is_stable_and_namespaced(self) -> None:
        assigned = derive_company_identity(
            salt="tenant-secret",
            company_name="예시기업",
            kma_assigned_code="KMA-0001",
        )
        assigned_again = derive_company_identity(
            salt="tenant-secret",
            company_name="변경된 표시명",
            kma_assigned_code="kma 0001",
        )
        business = derive_company_identity(
            salt="tenant-secret",
            company_name="예시기업",
            business_registration_number="0000000001",
        )
        self.assertEqual(assigned.company_id, assigned_again.company_id)
        self.assertNotEqual(assigned.company_id, business.company_id)
        self.assertEqual("kma_assigned", assigned.identity_source)
        self.assertNotIn("KMA-0001", repr(assigned))

    def test_exactly_one_identity_source_and_valid_shape_are_required(self) -> None:
        with self.assertRaisesRegex(TenantError, "중 하나만"):
            derive_company_identity(salt="secret", company_name="회사")
        with self.assertRaisesRegex(TenantError, "중 하나만"):
            derive_company_identity(
                salt="secret",
                company_name="회사",
                business_registration_number="1234567890",
                kma_assigned_code="KMA0001",
            )
        with self.assertRaisesRegex(TenantError, "10자리"):
            derive_company_identity(
                salt="secret",
                company_name="회사",
                business_registration_number="123",
            )

    def test_company_and_participant_codes_use_separate_namespaces(self) -> None:
        identity = derive_company_identity(
            salt="tenant-secret",
            kma_assigned_code="KMA0001",
        )
        company_digest = hash_company_access_code(
            identity.company_id,
            "abc",
            "access-secret",
        )
        participant_digest = hash_participant_access_code(
            identity.company_id,
            "abc",
            "access-secret",
            project_id="TAP-001",
        )
        self.assertRegex(company_digest, r"^cac_[0-9a-f]{64}$")
        self.assertRegex(participant_digest, r"^pac_[0-9a-f]{64}$")
        self.assertNotEqual(company_digest.removeprefix("cac_"), participant_digest.removeprefix("pac_"))
        self.assertTrue(
            verify_company_access_code(
                identity.company_id,
                "abc",
                company_digest,
                "access-secret",
            )
        )
        self.assertFalse(
            verify_company_access_code(
                identity.company_id,
                "wrong",
                company_digest,
                "access-secret",
            )
        )
        self.assertFalse(
            verify_company_access_code(
                identity.company_id,
                "abc",
                participant_digest,
                "access-secret",
            )
        )
        self.assertTrue(
            verify_participant_access_code(
                identity.company_id,
                "abc",
                participant_digest,
                "access-secret",
                project_id="TAP-001",
            )
        )
        self.assertFalse(
            verify_participant_access_code(
                identity.company_id,
                "abc",
                participant_digest,
                "access-secret",
                project_id="TAP-002",
            )
        )
        self.assertNotIn("abc", company_digest)
        self.assertNotIn("abc", participant_digest)

    def test_access_codes_share_nfkc_normalization_and_unicode_safe_compare(self) -> None:
        self.assertEqual("ABC", normalize_access_code("  ＡＢＣ  "))
        self.assertEqual("관리코드", validate_access_code(" 관리코드 "))
        self.assertTrue(access_codes_equal("ＡＢＣ", "ABC"))
        self.assertTrue(access_codes_equal("관리코드", "관리코드"))
        self.assertFalse(access_codes_equal("관리코드", "다른코드"))
        self.assertFalse(access_codes_equal("", ""))

        identity = derive_company_identity(
            salt="tenant-secret",
            kma_assigned_code="KMA0001",
        )
        digest = hash_company_access_code(
            identity.company_id,
            "ＡＢＣ",
            "access-secret",
        )
        self.assertTrue(
            verify_company_access_code(
                identity.company_id,
                "ABC",
                digest,
                "access-secret",
            )
        )


if __name__ == "__main__":
    unittest.main()
