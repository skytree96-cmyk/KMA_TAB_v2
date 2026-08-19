from __future__ import annotations

import ast
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tap import runtime_guard


ROOT = Path(__file__).resolve().parents[1]


class RuntimeGuardTests(unittest.TestCase):
    def _module(self, name: str, source: Path) -> types.ModuleType:
        module = types.ModuleType(name)
        module.__file__ = str(source)
        setattr(
            module,
            runtime_guard.SOURCE_FINGERPRINT_ATTRIBUTE,
            runtime_guard.source_fingerprint(str(source)),
        )
        return module

    def test_detects_module_and_release_changes_without_mutating_sys_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            source = temp / "sample_module.py"
            manifest = temp / "MANIFEST_SHA256.txt"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            manifest.write_text("release-one\n", encoding="utf-8")
            module_name = "tap_test_runtime_guard_sample"
            module = self._module(module_name, source)
            loaded_release = runtime_guard.source_fingerprint(str(manifest))

            with (
                patch.dict(sys.modules, {module_name: module}),
                patch.object(runtime_guard, "MANIFEST_PATH", manifest),
                patch.object(
                    runtime_guard,
                    "LOADED_RELEASE_FINGERPRINT",
                    loaded_release,
                ),
            ):
                self.assertEqual((), runtime_guard.stale_local_modules((module_name,)))
                self.assertIs(module, sys.modules[module_name])

                source.write_text("VALUE = 2\n", encoding="utf-8")
                self.assertEqual(
                    (module_name,),
                    runtime_guard.stale_local_modules((module_name,)),
                )
                self.assertIs(module, sys.modules[module_name])

                manifest.write_text("release-two\n", encoding="utf-8")
                stale = runtime_guard.stale_local_modules((module_name,))
                self.assertIn("TAP release manifest", stale)
                self.assertNotIn(module_name, stale)

    def test_release_mismatch_returns_before_importing_application_modules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "MANIFEST_SHA256.txt"
            manifest.write_text("new-release\n", encoding="utf-8")
            with (
                patch.object(runtime_guard, "MANIFEST_PATH", manifest),
                patch.object(runtime_guard, "LOADED_RELEASE_FINGERPRINT", "old-release"),
            ):
                self.assertEqual(
                    ("TAP release manifest",),
                    runtime_guard.stale_local_modules(("module_that_must_not_import",)),
                )

    def test_stop_on_stale_fails_closed_with_korean_maintenance_message(self) -> None:
        class FakeStreamlit:
            def __init__(self) -> None:
                self.messages: list[str] = []

            def error(self, message: str) -> None:
                self.messages.append(message)

            def stop(self) -> None:
                raise RuntimeError("stopped")

        fake = FakeStreamlit()
        with patch(
            "tap.runtime_guard.stale_local_modules",
            return_value=("tap.ui",),
        ):
            with self.assertRaisesRegex(RuntimeError, "stopped"):
                runtime_guard.stop_on_stale(fake, ("tap.ui",))

        self.assertEqual(1, len(fake.messages))
        self.assertIn("새 버전 배포", fake.messages[0])

    def test_every_streamlit_entrypoint_guards_before_symbol_imports(self) -> None:
        cases = {
            "streamlit_app.py": {"tap.open_page"},
            "pages/9_manager_dashboard.py": {
                "tap.dashboard",
                "tap.github_demo_store",
                "tap.ui",
            },
            "pages/0_user_guide.py": {"tap.ui"},
            "pages/1_project_setup.py": {"tap.github_demo_store", "tap.ui"},
            "pages/2_assessment.py": {
                "tap.baseline_transfer",
                "tap.github_demo_store",
                "tap.ui",
            },
            "pages/3_individual_report.py": {"tap.baseline_transfer", "tap.ui"},
            "pages/4_organization_report.py": {
                "tap.dashboard",
                "tap.github_demo_store",
                "tap.radar",
                "tap.ui",
            },
            "pages/5_question_bank.py": {"tap.ui"},
            "pages/6_kma_dashboard.py": {
                "tap.dashboard",
                "tap.github_demo_store",
                "tap.ui",
            },
            "pages/7_pre_assessment.py": {
                "tap.baseline_transfer",
                "tap.github_demo_store",
                "tap.ui",
            },
            "pages/8_post_assessment.py": {
                "tap.baseline_transfer",
                "tap.github_demo_store",
                "tap.ui",
            },
        }

        for relative_path, expected_modules in cases.items():
            with self.subTest(path=relative_path):
                source = (ROOT / relative_path).read_text(encoding="utf-8")
                tree = ast.parse(source, filename=relative_path)
                guard_calls = [
                    node
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "stop_on_stale"
                ]
                self.assertEqual(1, len(guard_calls))
                guard = guard_calls[0]
                self.assertGreaterEqual(len(guard.args), 2)
                guarded_modules = set(ast.literal_eval(guard.args[1]))
                self.assertEqual(expected_modules, guarded_modules)

                protected_imports = [
                    node
                    for node in tree.body
                    if isinstance(node, ast.ImportFrom)
                    and node.module in expected_modules
                ]
                if relative_path in {
                    "pages/7_pre_assessment.py",
                    "pages/8_post_assessment.py",
                }:
                    run_path_calls = [
                        node
                        for node in ast.walk(tree)
                        if isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Attribute)
                        and isinstance(node.func.value, ast.Name)
                        and node.func.value.id == "runpy"
                        and node.func.attr == "run_path"
                    ]
                    self.assertEqual(1, len(run_path_calls))
                    self.assertLess(guard.lineno, run_path_calls[0].lineno)
                    self.assertEqual([], protected_imports)
                else:
                    self.assertEqual(expected_modules, {node.module for node in protected_imports})
                    self.assertTrue(all(guard.lineno < node.lineno for node in protected_imports))
                self.assertFalse(
                    any(
                        isinstance(node, ast.Call)
                        and (
                            isinstance(node.func, ast.Name)
                            and node.func.id == "reload"
                            or isinstance(node.func, ast.Attribute)
                            and node.func.attr == "reload"
                        )
                        for node in ast.walk(tree)
                    )
                )

    def test_guarded_modules_record_their_import_time_source_hash(self) -> None:
        for module_name in (
            "tap.ui",
            "tap.dashboard",
            "tap.baseline_transfer",
            "tap.github_demo_store",
            "tap.radar",
            "tap.open_page",
        ):
            with self.subTest(module=module_name):
                module = sys.modules.get(module_name)
                if module is None:
                    module = __import__(module_name, fromlist=["*"])
                expected = runtime_guard.source_fingerprint(str(module.__file__))
                self.assertEqual(
                    expected,
                    getattr(module, runtime_guard.SOURCE_FINGERPRINT_ATTRIBUTE),
                )


if __name__ == "__main__":
    unittest.main()
