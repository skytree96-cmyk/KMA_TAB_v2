from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
import io
import os
import unittest
from unittest.mock import patch

from scripts import check_postgres_accounts as preflight

try:
    from psycopg.conninfo import conninfo_to_dict
except ImportError:
    conninfo_to_dict = None


class PostgresPreflightTests(unittest.TestCase):
    @unittest.skipIf(conninfo_to_dict is None, "psycopg/libpq parser is not installed")
    def test_options_roundtrip_through_real_libpq_uses_percent_spaces(self):
        schema = "tapcheck_" + "a" * 32
        source = "postgresql://tester:p%2Bword@localhost/check?sslmode=require&application_name=preflight&options=-csearch_path%3Dpublic"
        url = preflight._schema_url(source, schema)
        parsed = conninfo_to_dict(url)
        self.assertEqual(parsed["options"], f"-csearch_path={schema} -cstatement_timeout=15000 -clock_timeout=10000")
        self.assertEqual(parsed["password"], "p+word")
        self.assertEqual(parsed["sslmode"], "require")
        self.assertEqual(parsed["application_name"], "preflight")
        self.assertNotIn("public", parsed["options"])
        # Reproduce the prior failure at the actual libpq boundary. Python's
        # parse_qs would hide this bug by treating literal '+' as a space.
        broken = conninfo_to_dict(url.replace("%20", "+"))
        self.assertNotEqual(broken["options"], parsed["options"])
        self.assertIn("+-cstatement_timeout", broken["options"])
        self.assertNotIn(" ", broken["options"])

    def test_generated_schema_guard_rejects_public_and_sql_fragments(self):
        for schema in ("public", "tapcheck_", "tapcheck_" + "a" * 31, "tapcheck_" + "a" * 32 + ";DROP"):
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                preflight._schema_url("postgresql://tester@localhost/check", schema)

    def test_render_database_requires_explicit_double_opt_in(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"DATABASE_URL": "SECRET_DSN_SENTINEL"}, clear=True), redirect_stdout(output):
            self.assertEqual(preflight.main([]), 1)
            self.assertEqual(preflight.main(["--render-preflight"]), 1)
        self.assertIn("stage=configuration", output.getvalue())
        self.assertNotIn("SECRET_DSN_SENTINEL", output.getvalue())

    def test_database_diagnostics_keep_stage_and_hide_raw_error(self):
        @contextmanager
        def failed_schema(dsn):
            with preflight._diagnostic_stage("schema-isolation"):
                raise RuntimeError("SECRET_DSN_SENTINEL password=SECRET_PASSWORD SELECT private_data")
            yield "unreachable"

        output = io.StringIO()
        with patch.dict(os.environ, {"TEST_DATABASE_URL": "SECRET_DSN_SENTINEL"}, clear=True):
            with patch.object(preflight, "_isolated_schema", failed_schema), redirect_stdout(output):
                self.assertEqual(preflight.main([]), 1)
        self.assertEqual(output.getvalue().strip(), "POSTGRES ACCOUNT CHECK FAILED: RuntimeError; stage=schema-isolation")
        self.assertNotIn("SECRET", output.getvalue())
        self.assertNotIn("SELECT", output.getvalue())


if __name__ == "__main__":
    unittest.main()
