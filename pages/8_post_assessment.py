"""Dedicated entry point for the education post-assessment.

The forced phase is reapplied on every rerun, including after a project code
is loaded, so a stored project's previous phase cannot send the participant
back to the pre-assessment unexpectedly.
"""

from __future__ import annotations

import runpy
from pathlib import Path

import streamlit as st

from tap.runtime_guard import stop_on_stale


stop_on_stale(st, ("tap.baseline_transfer", "tap.github_demo_store", "tap.ui"))

runpy.run_path(
    str(Path(__file__).with_name("2_assessment.py")),
    init_globals={"TAP_FORCED_ASSESSMENT_PHASE": "post"},
)
