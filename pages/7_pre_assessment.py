"""Dedicated entry point for the education pre-assessment.

The assessment implementation stays in the legacy page so existing bookmarks
remain valid, while this registered page gives the sidebar a distinct URL and
an unambiguous phase.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import streamlit as st

from tap.runtime_guard import stop_on_stale


stop_on_stale(st, ("tap.baseline_transfer", "tap.github_demo_store", "tap.ui"))

runpy.run_path(
    str(Path(__file__).with_name("2_assessment.py")),
    init_globals={"TAP_FORCED_ASSESSMENT_PHASE": "pre"},
)
