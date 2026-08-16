from __future__ import annotations

import hashlib
import hmac
from importlib import import_module
from pathlib import Path
from typing import Any, Iterable


SOURCE_FINGERPRINT_ATTRIBUTE = "__tap_source_sha256__"
MANIFEST_PATH = Path(__file__).resolve().parents[1] / "MANIFEST_SHA256.txt"


def source_fingerprint(module_file: str) -> str:
    """Return the on-disk fingerprint a local module records at import time."""

    return hashlib.sha256(Path(module_file).read_bytes()).hexdigest()


def _optional_source_fingerprint(path: Path) -> str:
    try:
        return source_fingerprint(str(path))
    except OSError:
        return ""


LOADED_RELEASE_FINGERPRINT = _optional_source_fingerprint(MANIFEST_PATH)


def stale_local_modules(module_names: Iterable[str]) -> tuple[str, ...]:
    """Find cached TAP modules whose loaded revision differs from disk.

    Streamlit sessions share Python's module cache. A deployment must never
    repair that cache with ``importlib.reload`` while another session is using
    the same module, because reload mutates the shared module dictionary and
    replaces exception classes in place. Each guarded module therefore records
    its source hash once, during a normal import. Entry pages compare that
    immutable import-time value with the current file and fail closed when a
    deployment has mixed revisions. The hosting process can then restart
    cleanly without any cross-session mutation.
    """

    stale: list[str] = []
    current_release_fingerprint = _optional_source_fingerprint(MANIFEST_PATH)
    if not current_release_fingerprint or not hmac.compare_digest(
        LOADED_RELEASE_FINGERPRINT,
        current_release_fingerprint,
    ):
        # Do not import any more application modules from a partially deployed
        # revision. The page can now show one stable maintenance message.
        return ("TAP release manifest",)
    for module_name in module_names:
        module = import_module(module_name)
        loaded_fingerprint = str(
            getattr(module, SOURCE_FINGERPRINT_ATTRIBUTE, "")
        )
        module_file = getattr(module, "__file__", None)
        if not loaded_fingerprint or not module_file:
            stale.append(module_name)
            continue
        try:
            current_fingerprint = source_fingerprint(str(module_file))
        except OSError:
            stale.append(module_name)
            continue
        if not hmac.compare_digest(loaded_fingerprint, current_fingerprint):
            stale.append(module_name)
    return tuple(stale)


def stop_on_stale(st: Any, module_names: Iterable[str]) -> None:
    """Stop a Streamlit entry page before it can use mixed-release modules."""

    if stale_local_modules(module_names):
        st.error("새 버전 배포를 적용하고 있습니다. 잠시 후 페이지를 새로고침해 주세요.")
        st.stop()
