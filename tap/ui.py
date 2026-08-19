from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import streamlit as st
from streamlit.errors import StreamlitAPIException, StreamlitPageNotFoundError

from tap.config import APP_TITLE, PROJECT_ROOT
from tap.runtime_guard import source_fingerprint


__tap_source_sha256__ = source_fingerprint(__file__)


ROLE_LABELS = {
    "company": "교육담당자",
    "participant": "참여자",
    "kma": "KMA 관리자",
}

ROLE_LANDINGS = {
    "company": "pages/9_manager_dashboard.py",
    "participant": "pages/7_pre_assessment.py",
    "kma": "pages/6_kma_dashboard.py",
}

ROLE_NAV = {
    "company": (
        ("pages/0_user_guide.py", "처음 사용 안내"),
        ("pages/9_manager_dashboard.py", "관리자 대시보드"),
        ("pages/1_project_setup.py", "교육평가 프로젝트"),
        ("pages/4_organization_report.py", "교육 전후 리포트"),
        ("pages/7_pre_assessment.py", "교육 전 검사"),
        ("pages/8_post_assessment.py", "교육 후 검사"),
    ),
    "participant": (
        ("pages/0_user_guide.py", "처음 사용 안내"),
        ("pages/7_pre_assessment.py", "교육 전 검사"),
        ("pages/8_post_assessment.py", "교육 후 검사"),
        ("pages/3_individual_report.py", "내 변화 리포트"),
    ),
    "kma": (
        ("pages/0_user_guide.py", "처음 사용 안내"),
        ("pages/6_kma_dashboard.py", "KMA 대시보드"),
        ("pages/5_question_bank.py", "문항은행·검수"),
        ("pages/9_manager_dashboard.py", "회원사 운영 화면"),
    ),
}


MOCKUP_CSS = """
<style>
  @import url('https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/static/pretendard.css');

  :root {
    --tap-ink:#102a2d;
    --tap-muted:#53696b;
    --tap-teal:#087b76;
    --tap-teal-deep:#075e5a;
    --tap-mint:#dff4f1;
    --tap-mint-2:#eff9f7;
    --tap-line:#d8e4e2;
    --tap-paper:#ffffff;
    --tap-canvas:#f4f8f7;
    --tap-coral:#ff735c;
    --tap-amber:#e7a825;
    --tap-blue:#4b7bec;
    --tap-option:#f7faf9;
    --tap-option-hover:#eef8f6;
    --tap-option-selected:#def3ef;
    --tap-option-zero:#f1f5f4;
    --tap-shadow:0 18px 52px rgba(14,68,65,.10);
    --tap-radius:20px;
  }

  html, body, .stApp, button, input, textarea, select {
    font-family:Pretendard,"Noto Sans KR","Malgun Gothic",system-ui,-apple-system,"Segoe UI",sans-serif;
  }
  [data-testid="stIconMaterial"],
  .material-symbols-rounded,
  .material-symbols-outlined {
    font-family:"Material Symbols Rounded","Material Symbols Outlined" !important;
    font-weight:normal !important;
    font-style:normal !important;
    letter-spacing:normal !important;
    text-transform:none !important;
    white-space:nowrap !important;
    word-wrap:normal !important;
    direction:ltr !important;
    font-feature-settings:"liga" !important;
  }
  .stApp { background:var(--tap-canvas) !important; color:var(--tap-ink) !important; }
  [data-testid="stSidebarNav"] { display:none !important; }
  .block-container {
    max-width:1240px;
    padding-top:2.15rem;
    padding-bottom:4rem;
  }
  h1, h2, h3, h4 { color:var(--tap-ink); letter-spacing:-.025em; }
  h1 { letter-spacing:-.045em; }
  p { line-height:1.62; }
  #MainMenu, footer { visibility:hidden; }
  [data-testid="stHeader"] {
    height:70px;
    background:var(--tap-paper);
    border-bottom:1px solid var(--tap-line);
    backdrop-filter:blur(12px);
  }
  [data-testid="stSidebar"] {
    background:var(--tap-paper);
    border-right:1px solid var(--tap-line);
  }
  [data-testid="stSidebar"] > div:first-child { padding-top:.85rem; }
  [data-testid="stSidebar"] hr { border-color:var(--tap-line); }
  [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"] {
    border-radius:11px;
    min-height:43px;
    color:var(--tap-muted);
    font-size:.9rem;
    font-weight:720;
    padding:.6rem .75rem;
  }
  [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"]:hover {
    background:var(--tap-mint-2);
    color:var(--tap-teal-deep);
  }
  [data-testid="stSidebar"] [data-testid="stPageLink-NavLink"][aria-current="page"] {
    background:var(--tap-mint);
    color:var(--tap-teal-deep);
  }
  [data-testid="stSidebar"] [data-testid="stButton"] {
    margin-bottom:.34rem;
  }
  [data-testid="stSidebar"] [data-testid="stButton"] > button {
    justify-content:flex-start;
    padding:.45rem .7rem;
  }
  [data-testid="stSidebar"] [data-testid="stButton"] > button[kind="primary"] {
    border-color:#9edbd5;
    background:var(--tap-mint);
    color:var(--tap-teal-deep);
    box-shadow:0 2px 8px rgba(20,63,61,.10);
  }
  [data-testid="stSidebar"] [data-testid="stButton"]:has(button[kind="primary"]) {
    border-radius:11px;
  }
  [data-testid="stSidebar"] .stDownloadButton > button {
    min-height:38px;
    margin-top:.4rem;
    border-color:#bfe8e3;
    background:var(--tap-mint-2);
    color:var(--tap-teal-deep);
    font-size:.78rem;
  }

  .tap-brand {
    display:flex;
    align-items:center;
    gap:11px;
    margin:.05rem 0 .8rem;
  }
  .tap-brandmark {
    width:42px;
    height:42px;
    border-radius:13px;
    background:linear-gradient(145deg,#00b9ad,#087b76);
    display:grid;
    place-items:center;
    color:#fff;
    font-weight:900;
    letter-spacing:-1px;
    box-shadow:0 8px 24px rgba(8,169,159,.25);
  }
  .tap-brand strong { display:block; color:var(--tap-ink); font-size:18px; letter-spacing:-.4px; }
  .tap-brand small { display:block; color:var(--tap-muted); font-size:11px; }
  .tap-beta {
    display:inline-flex;
    align-items:center;
    gap:6px;
    margin:.15rem 0 .85rem;
    border:1px solid #bfe8e3;
    background:var(--tap-mint-2);
    color:var(--tap-teal-deep);
    padding:6px 9px;
    border-radius:999px;
    font-size:11px;
    font-weight:800;
  }
  .tap-beta:before { content:""; width:7px; height:7px; border-radius:50%; background:var(--tap-teal); }
  .tap-side-label {
    margin:.45rem .25rem .35rem;
    color:#586d6e;
    font-size:11px;
    font-weight:900;
    letter-spacing:.12em;
  }
  .tap-side-note {
    margin-top:1rem;
    border:1px solid #cbe6e2;
    border-radius:15px;
    background:linear-gradient(145deg,var(--tap-mint-2),var(--tap-paper));
    padding:14px;
    color:var(--tap-muted);
    font-size:12px;
    line-height:1.55;
  }
  .tap-side-note b { display:block; color:var(--tap-ink); font-size:13px; margin-bottom:4px; }

  .tap-page-head {
    display:flex;
    align-items:flex-start;
    justify-content:space-between;
    gap:20px;
    margin-bottom:24px;
  }
  .tap-eyebrow {
    color:var(--tap-teal-deep);
    font-size:12px;
    font-weight:900;
    letter-spacing:.11em;
    text-transform:uppercase;
    margin-bottom:8px;
  }
  .tap-page-head h1 {
    margin:0;
    color:var(--tap-ink);
    font-size:31px;
    line-height:1.18;
    letter-spacing:-1.2px;
  }
  .tap-page-head p { margin:9px 0 0; color:var(--tap-muted); font-size:15px; }
  .tap-chip {
    display:inline-flex;
    align-items:center;
    border-radius:999px;
    padding:6px 10px;
    background:var(--tap-mint-2);
    color:var(--tap-muted);
    font-size:11px;
    font-weight:850;
    white-space:nowrap;
  }
  .tap-chip.teal { background:var(--tap-mint); color:var(--tap-teal-deep); }
  .tap-chip.coral { background:#fff0ec; color:#963728; }
  .tap-chip.amber { background:#fff6df; color:#715000; }
  .tap-chip.blue { background:#eef2ff; color:#304a9c; }

  .tap-hero {
    position:relative;
    overflow:hidden;
    background:linear-gradient(125deg,#0c3032 0%,#0b5552 56%,#08a99f 100%);
    border-radius:28px;
    color:#fff;
    padding:38px 42px;
    min-height:260px;
    box-shadow:var(--tap-shadow);
    display:grid;
    grid-template-columns:1.25fr .75fr;
    gap:28px;
    align-items:center;
    margin-bottom:18px;
  }
  .tap-hero:after {
    content:"";
    position:absolute;
    width:420px;
    height:420px;
    border:1px solid rgba(255,255,255,.19);
    border-radius:50%;
    right:-125px;
    top:-105px;
    box-shadow:0 0 0 58px rgba(255,255,255,.04),0 0 0 118px rgba(255,255,255,.025);
  }
  .tap-hero-copy, .tap-loop-card { position:relative; z-index:2; }
  .tap-hero h2 { color:#fff; font-size:34px; line-height:1.18; letter-spacing:-1.5px; margin:10px 0 14px; }
  .tap-hero p { color:#d9f2ef; margin:0; max-width:650px; }
  .tap-loop-card {
    background:rgba(255,255,255,.12);
    border:1px solid rgba(255,255,255,.22);
    border-radius:21px;
    padding:23px;
    backdrop-filter:blur(9px);
  }
  .tap-loop-step { display:flex; align-items:center; gap:12px; margin:8px 0; font-weight:800; }
  .tap-loop-step span {
    width:28px; height:28px; border-radius:50%; background:#fff; color:var(--tap-teal-deep);
    display:grid; place-items:center; font-weight:900; font-size:12px;
  }
  .tap-loop-arrow { height:13px; border-left:1px dashed rgba(255,255,255,.45); margin-left:14px; }

  .tap-stats { display:grid; grid-template-columns:repeat(4,1fr); gap:14px; margin:18px 0 26px; }
  .tap-stat { background:var(--tap-paper); border:1px solid var(--tap-line); border-radius:17px; padding:19px; }
  .tap-stat b { display:block; color:var(--tap-ink); font-size:25px; letter-spacing:-1px; }
  .tap-stat span { display:block; color:var(--tap-muted); font-size:12px; margin-top:4px; }
  .tap-stat small { display:block; color:var(--tap-teal-deep); font-weight:800; font-size:11px; margin-top:8px; }
  .tap-project-row {
    display:grid;
    grid-template-columns:1.5fr .75fr .55fr .45fr;
    gap:12px;
    align-items:center;
    padding:14px 0;
    border-top:1px solid #edf2f1;
  }
  .tap-project-row:first-child { border-top:0; }
  .tap-project-row b { color:var(--tap-ink); font-size:14px; }
  .tap-project-row small { display:block; color:var(--tap-muted); margin-top:3px; font-size:11px; }
  .tap-progress { height:8px; background:#e8f0ef; border-radius:999px; overflow:hidden; }
  .tap-progress i { display:block; height:100%; background:linear-gradient(90deg,var(--tap-teal),#51d1c5); border-radius:999px; }
  .tap-project-metric { color:var(--tap-ink); font-size:13px; font-weight:850; }

  .tap-callout {
    display:flex;
    gap:12px;
    padding:15px 17px;
    border-radius:14px;
    border:1px solid #cbe8e4;
    background:#f3fbfa;
    color:#315f5d;
    font-size:13px;
    line-height:1.55;
    margin-bottom:10px;
  }
  .tap-callout.warn { border-color:#f1dfb5; background:#fffaf0; color:#76591e; }
  .tap-callout.danger { border-color:#ffd0c8; background:#fff5f3; color:#8f4338; }
  .tap-callout .tap-callout-icon { min-width:23px; font-weight:900; }
  .tap-callout strong { color:inherit; }
  .tap-summary-strip {
    display:flex;
    gap:18px;
    align-items:center;
    flex-wrap:wrap;
    background:#0d3334;
    color:#fff;
    border-radius:15px;
    padding:15px 18px;
    margin:15px 0 18px;
  }
  .tap-summary-item { min-width:110px; }
  .tap-summary-item b { display:block; color:#fff; font-size:19px; }
  .tap-summary-item span { color:#bfe4df; font-size:11px; }
  .tap-domain-head {
    display:flex;
    align-items:center;
    justify-content:space-between;
    margin:1.3rem 0 .65rem;
    padding:.7rem .85rem;
    background:var(--tap-mint-2);
    border:1px solid var(--tap-line);
    border-radius:13px;
  }
  .tap-domain-head b { font-size:14px; }
  .tap-domain-head span { color:var(--tap-muted); font-size:11px; }
  .tap-question-stage-anchor { display:block; width:0; height:0; overflow:hidden; }
  .stApp [data-testid="stVerticalBlockBorderWrapper"]:has(.tap-question-stage-anchor) {
    max-width:980px;
    margin:22px auto 30px;
    padding:clamp(20px,3.2vw,42px) !important;
    border:1px solid var(--tap-line) !important;
    border-radius:28px !important;
    background:var(--tap-paper) !important;
    box-shadow:0 22px 60px rgba(18,65,62,.10) !important;
  }
  .tap-assessment-progress-head { display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:10px; }
  .tap-assessment-progress-count { display:flex; align-items:baseline; gap:5px; }
  .tap-assessment-progress-count b { color:var(--tap-ink); font-size:24px; letter-spacing:-.04em; }
  .tap-assessment-progress-count span,.tap-assessment-progress-status { color:var(--tap-muted); font-size:12px; font-weight:700; }
  .tap-question-panel { padding:clamp(30px,5vw,58px) 0 clamp(28px,4vw,48px); text-align:center; }
  .tap-question-meta {
    display:flex;
    align-items:center;
    justify-content:center;
    gap:8px;
    flex-wrap:wrap;
    margin-bottom:22px;
  }
  .tap-factor-pill,.tap-period-pill { display:inline-flex; align-items:center; min-height:30px; border-radius:999px; padding:5px 11px; font-size:11px; font-weight:850; }
  .tap-factor-pill { background:var(--tap-mint); color:var(--tap-teal-deep); }
  .tap-period-pill { border:1px solid var(--tap-line); background:var(--tap-option); color:var(--tap-muted); }
  .tap-question-number { margin:0 0 11px; color:var(--tap-muted); font-size:12px; font-weight:800; letter-spacing:.08em; }
  .tap-question-panel h2 {
    max-width:790px;
    margin:0 auto;
    color:var(--tap-ink);
    font-size:clamp(24px,3vw,34px);
    line-height:1.4;
    letter-spacing:-1px;
    text-wrap:balance;
  }
  .tap-response-head { display:flex; align-items:flex-end; justify-content:space-between; gap:12px; padding-top:24px; border-top:1px solid var(--tap-line); margin-bottom:14px; }
  .tap-response-head b { color:var(--tap-ink); font-size:14px; }
  .tap-response-head span { color:var(--tap-muted); font-size:11px; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) { padding:0; border:0; background:transparent; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadio"] [role="radiogroup"] {
    display:grid !important;
    grid-template-columns:repeat(6,minmax(0,1fr));
    gap:10px;
    align-items:stretch;
  }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"] {
    position:relative;
    display:flex !important;
    flex-direction:column;
    align-items:center;
    justify-content:center;
    gap:8px;
    min-width:0;
    min-height:118px;
    margin:0 !important;
    padding:16px 8px 13px !important;
    overflow:hidden;
    border:1px solid var(--tap-line);
    border-radius:16px;
    background:var(--tap-option);
    cursor:pointer;
    transition:border-color .16s ease,background .16s ease,box-shadow .16s ease,transform .16s ease;
  }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]:hover {
    border-color:#8bcfc8;
    background:var(--tap-option-hover);
    box-shadow:0 7px 18px rgba(11,89,83,.08);
    transform:translateY(-2px);
  }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"] > div:first-child { position:absolute; width:1px; height:1px; overflow:hidden; opacity:0; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]::before {
    content:"";
    display:grid;
    place-items:center;
    width:42px;
    height:42px;
    flex:0 0 42px;
    border-radius:13px;
    background:var(--tap-paper);
    border:1px solid var(--tap-line);
    color:var(--tap-muted);
    font-size:19px;
    font-weight:900;
    line-height:1;
  }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]:nth-child(1)::before { content:"0"; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]:nth-child(2)::before { content:"1"; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]:nth-child(3)::before { content:"2"; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]:nth-child(4)::before { content:"3"; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]:nth-child(5)::before { content:"4"; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]:nth-child(6)::before { content:"5"; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]:first-child { border-style:dashed; background:var(--tap-option-zero); }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"] p { margin:0; color:var(--tap-ink) !important; font-size:12px; font-weight:750; line-height:1.35; text-align:center; word-break:keep-all; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]:has(input:checked),
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"][data-selected] {
    border-color:var(--tap-teal) !important;
    border-style:solid;
    background:var(--tap-option-selected) !important;
    box-shadow:0 0 0 2px color-mix(in srgb,var(--tap-teal) 22%,transparent);
  }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]:has(input:checked)::before,
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"][data-selected]::before { border-color:var(--tap-teal); background:var(--tap-teal); color:#fff; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]:has(input:checked) p,
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"][data-selected] p { color:var(--tap-teal-deep) !important; font-weight:900; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stFormSubmitButton"] { margin-top:18px; }
  .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stFormSubmitButton"] > button { min-height:50px; border-radius:14px; font-size:14px; }
  .tap-report-hero {
    background:linear-gradient(135deg,var(--tap-paper),var(--tap-mint-2));
    border:1px solid #cfe7e3;
    border-radius:25px;
    padding:28px;
    display:grid;
    grid-template-columns:1.3fr .7fr;
    gap:25px;
    margin-bottom:18px;
  }
  .tap-report-hero h2 { margin:8px 0; color:var(--tap-ink); font-size:27px; }
  .tap-report-hero p { margin:0; color:var(--tap-muted); font-size:13px; }
  .tap-score-callout { background:#0c3334; border-radius:20px; color:#fff; padding:22px; }
  .tap-score-callout b { display:block; color:#fff; font-size:32px; }
  .tap-score-callout small { color:#bfe0dc; }
  .tap-insight { border-left:4px solid var(--tap-teal); padding:3px 0 3px 15px; margin:16px 0; }
  .tap-insight.coral { border-color:var(--tap-coral); }
  .tap-insight h4 { margin:0 0 5px; font-size:14px; }
  .tap-insight p { margin:0; color:var(--tap-muted); font-size:13px; }
  .tap-card-title { margin:0 0 4px; color:var(--tap-ink); font-size:17px; }
  .tap-card-sub { margin:0 0 14px; color:var(--tap-muted); font-size:13px; }
  .tap-kicker { color:var(--tap-teal-deep); font-weight:900; font-size:.78rem; letter-spacing:.09em; }
  .tap-note { padding:.9rem 1rem; border-left:4px solid var(--tap-teal); background:var(--tap-mint-2); border-radius:8px; color:var(--tap-ink); }
  .small-muted { color:var(--tap-muted); font-size:.82rem; }

  .tap-guide-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:13px; margin:18px 0 24px; }
  .tap-guide-step { position:relative; background:var(--tap-paper); border:1px solid var(--tap-line); border-radius:17px; padding:20px; min-height:150px; }
  .tap-guide-step>span { display:grid; place-items:center; width:30px; height:30px; border-radius:50%; background:var(--tap-teal); color:#fff; font-weight:900; font-size:12px; }
  .tap-guide-step b { display:block; color:var(--tap-ink); margin:17px 0 6px; font-size:15px; }
  .tap-guide-step small { display:block; color:var(--tap-muted); line-height:1.55; }

  .tap-report-document { display:grid; gap:24px; margin:18px auto 30px; }
  .tap-report-sheet {
    color-scheme:light;
    position:relative;
    min-height:860px;
    padding:50px 54px 62px;
    overflow:hidden;
    background:#fff;
    color:#102a2d;
    border:1px solid #d8e4e2;
    border-radius:6px;
    box-shadow:0 20px 58px rgba(14,49,48,.12);
  }
  .tap-report-sheet h1,.tap-report-sheet h2,.tap-report-sheet h3,.tap-report-sheet b,.tap-report-sheet strong { color:#102a2d; }
  .tap-report-brand { display:flex; align-items:center; gap:10px; margin-bottom:120px; }
  .tap-report-brand>span { width:40px; height:40px; border-radius:11px; display:grid; place-items:center; background:#087b76; color:#fff; font-weight:900; }
  .tap-report-brand b,.tap-report-brand small { display:block; }
  .tap-report-brand small { color:#53696b; font-size:10px; }
  .tap-report-kicker { color:#087b76; font-size:11px; font-weight:900; letter-spacing:.12em; margin-bottom:9px; }
  .tap-report-sheet h1 { font-size:34px; margin:0; letter-spacing:-1.4px; }
  .tap-report-sheet h2 { font-size:25px; margin:0 0 8px; letter-spacing:-.9px; }
  .tap-report-lead,.tap-report-desc { color:#53696b; line-height:1.65; }
  .tap-report-lead { max-width:760px; font-size:15px; }
  .tap-report-desc { margin:0 0 22px; font-size:12px; }
  .tap-report-meta { display:flex; gap:14px; margin:22px 0; padding:13px 0; border-top:1px solid #d8e4e2; border-bottom:1px solid #d8e4e2; color:#53696b; font-size:11px; }
  .tap-report-meta b { margin-right:auto; }
  .tap-report-kpis { display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin:24px 0; }
  .tap-report-kpis div { border:1px solid #d8e4e2; border-radius:14px; padding:15px; }
  .tap-report-kpis b,.tap-report-kpis span { display:block; }
  .tap-report-kpis b { font-size:22px; }
  .tap-report-kpis span { color:#53696b; font-size:10px; margin-top:4px; }
  .tap-report-summary { padding:19px; border-left:4px solid #087b76; background:#eff9f7; border-radius:9px; font-size:13px; line-height:1.65; }
  .tap-report-watermark { position:absolute; right:54px; top:44px; border:1px solid #ffd0c8; border-radius:99px; padding:5px 9px; background:#fff0ec; color:#963728; font-size:9px; font-weight:900; }
  .tap-report-sheet footer { visibility:visible; position:absolute; left:54px; right:54px; bottom:27px; padding-top:9px; border-top:1px solid #d8e4e2; color:#708382; font-size:9px; }
  .tap-report-score-list { display:grid; gap:5px; }
  .tap-report-score-row { display:grid; grid-template-columns:180px 1fr 48px; gap:11px; align-items:center; padding:10px 0; border-bottom:1px solid #edf2f1; }
  .tap-report-score-row b,.tap-report-score-row small { display:block; }
  .tap-report-score-row b { font-size:12px; }
  .tap-report-score-row small { color:#53696b; font-size:9px; margin-top:2px; }
  .tap-report-score-row>strong { text-align:right; font-size:12px; }
  .tap-report-bar { height:10px; background:#e8f0ef; border-radius:99px; overflow:hidden; }
  .tap-report-bar i { display:block; height:100%; border-radius:99px; background:linear-gradient(90deg,#25c3b5,#087b76); }
  .tap-report-method,.tap-report-warning { display:flex; gap:14px; margin-top:20px; padding:14px 16px; border-radius:12px; background:#eff9f7; font-size:11px; }
  .tap-report-method b,.tap-report-warning b { min-width:120px; }
  .tap-report-method span,.tap-report-warning span { color:#53696b; }
  .tap-report-warning { border:1px solid #f1dfb5; background:#fffaf0; }
  .tap-report-priority-list { display:grid; gap:12px; }
  .tap-report-priority { display:grid; grid-template-columns:30px 1fr auto; gap:12px; align-items:center; border:1px solid #d8e4e2; border-radius:14px; padding:15px; }
  .tap-report-priority>span { width:30px; height:30px; border-radius:50%; display:grid; place-items:center; background:#087b76; color:#fff; font-weight:900; }
  .tap-report-priority b,.tap-report-priority small { display:block; }
  .tap-report-priority small { color:#53696b; margin-top:3px; }
  .tap-report-priority em { border-radius:99px; padding:5px 8px; background:#fff0ec; color:#963728; font-size:9px; font-style:normal; }
  .tap-report-table { width:100%; border-collapse:collapse; margin-top:17px; }
  .tap-report-table th,.tap-report-table td { padding:10px 8px; border-bottom:1px solid #e7efee; font-size:10px; text-align:right; }
  .tap-report-table th { background:#f7faf9; color:#53696b; }
  .tap-report-table th:first-child,.tap-report-table td:first-child { text-align:left; }
  .tap-report-method-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; margin-top:20px; }
  .tap-report-method-grid div { padding:13px; border:1px solid #d8e4e2; border-radius:11px; }
  .tap-report-method-grid b,.tap-report-method-grid span { display:block; }
  .tap-report-method-grid b { font-size:10px; }
  .tap-report-method-grid span { color:#53696b; font-size:9px; line-height:1.5; margin-top:4px; }

  [data-testid="stMetric"] {
    background:var(--tap-paper);
    border:1px solid var(--tap-line);
    padding:1rem;
    border-radius:17px;
    box-shadow:none;
  }
  [data-testid="stMetricLabel"] { color:var(--tap-muted); }
  [data-testid="stMetricValue"] { color:var(--tap-ink); letter-spacing:-.04em; }
  [data-testid="stVerticalBlockBorderWrapper"] {
    border-color:var(--tap-line) !important;
    border-radius:var(--tap-radius) !important;
    background:var(--tap-paper);
    box-shadow:none;
  }
  [data-testid="stVerticalBlockBorderWrapper"]:has(input[type="checkbox"]:checked) {
    border-color:#89d6ce !important;
    background:var(--tap-mint-2);
  }
  [data-testid="stCheckbox"] label { align-items:flex-start; }
  [data-testid="stCheckbox"] label p { color:var(--tap-ink); font-weight:780; }
  [data-testid="stCheckbox"] input { accent-color:var(--tap-teal); }
  [data-testid="stCheckbox"]:has(input:disabled) { opacity:1; }
  [data-testid="stCheckbox"]:has(input:disabled) label p { color:var(--tap-muted); }
  .stButton > button, .stDownloadButton > button, .stLinkButton > a {
    min-height:42px;
    border-radius:11px;
    border-color:var(--tap-line);
    background:var(--tap-paper);
    color:var(--tap-ink);
    font-weight:800;
    transition:.16s ease;
  }
  .stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover {
    border-color:#8bcfc8;
    color:var(--tap-teal-deep);
    transform:translateY(-1px);
    box-shadow:0 6px 16px rgba(12,67,63,.08);
  }
  .stButton > button[kind="primary"] {
    background:var(--tap-teal);
    border-color:var(--tap-teal);
    color:#fff;
  }
  .stButton > button[kind="primary"]:hover { background:var(--tap-teal-deep); color:#fff; }
  [data-baseweb="input"] > div,
  [data-baseweb="select"] > div,
  [data-testid="stDateInput"] [data-baseweb="input"] > div,
  [data-testid="stTextInput"] [data-baseweb="input"] > div {
    border-color:var(--tap-line) !important;
    border-radius:10px !important;
    background:var(--tap-paper);
    color:var(--tap-ink);
  }
  .stApp [data-testid="stWidgetLabel"] p,
  .stApp [data-testid="stRadio"] label p,
  .stApp [data-testid="stFileUploader"] p,
  .stApp [data-testid="stExpander"] p {
    color:var(--tap-ink);
  }
  .stApp [data-testid="stRadioOption"],
  .stApp [data-testid="stRadioOption"] p {
    color:var(--tap-ink) !important;
  }
  .stApp [data-testid="stRadioOption"][data-selected] p {
    color:var(--tap-teal-deep) !important;
    font-weight:800;
  }
  .stApp [data-testid="stCaptionContainer"] p { color:var(--tap-muted) !important; }
  [data-testid="stFileUploaderDropzone"] {
    border-color:var(--tap-line) !important;
    background:var(--tap-mint-2) !important;
    color:var(--tap-ink) !important;
  }
  [data-baseweb="input"] input,
  [data-baseweb="select"] input,
  .stApp textarea {
    color:var(--tap-ink) !important;
    caret-color:var(--tap-teal) !important;
  }
  [data-testid="stTextInput"] input:disabled {
    -webkit-text-fill-color:var(--tap-ink) !important;
    color:var(--tap-ink) !important;
    opacity:1 !important;
    cursor:not-allowed;
  }
  [data-baseweb="input"] input::placeholder,
  .stApp textarea::placeholder { color:var(--tap-muted) !important; opacity:.82; }
  [data-testid="stSlider"] [role="slider"] { background:var(--tap-teal); }
  .stApp [data-testid="stProgress"] > div:first-child,
  .stApp [data-testid="stProgress"] > div:first-child p {
    color:var(--tap-ink) !important;
    background:transparent !important;
  }
  .stApp [data-testid="stProgressBarTrack"] {
    background:var(--tap-line) !important;
  }
  .stApp [data-testid="stProgressBarTrack"] > div {
    background:linear-gradient(90deg,var(--tap-teal),#51d1c5) !important;
  }
  [data-testid="stDataFrame"] { border:1px solid var(--tap-line); border-radius:15px; overflow:hidden; }
  [data-testid="stAlert"] { border-radius:14px; }
  [data-testid="stTabs"] [data-baseweb="tab-list"] { gap:.35rem; }
  [data-testid="stTabs"] button[aria-selected="true"] { color:var(--tap-teal-deep); border-bottom-color:var(--tap-teal); }

  @media (prefers-color-scheme:dark) {
    :root {
      --tap-ink:#e7f2f0;
      --tap-muted:#adc0be;
      --tap-teal:#5ed1c7;
      --tap-teal-deep:#8be1d9;
      --tap-mint:#173f3c;
      --tap-mint-2:#102f2d;
      --tap-line:#355452;
      --tap-paper:#112625;
      --tap-canvas:#0b1919;
      --tap-coral:#ff9b89;
      --tap-amber:#f1c35b;
      --tap-blue:#91a9ff;
      --tap-option:#172e2d;
      --tap-option-hover:#1b3937;
      --tap-option-selected:#1b4743;
      --tap-option-zero:#1a2929;
      --tap-shadow:0 18px 52px rgba(0,0,0,.28);
    }
    [data-testid="stHeader"], [data-testid="stSidebar"] { background:var(--tap-paper) !important; }
    .tap-callout { border-color:#3b5f5c; background:#143633; color:#c6e5e1; }
    .tap-callout.warn { border-color:#765f35; background:#332b19; color:#f0d69a; }
    .tap-callout.danger { border-color:#754a44; background:#39201e; color:#ffc0b5; }
    [data-baseweb="input"] input, [data-baseweb="select"] input { color:var(--tap-ink) !important; }
  }

  @media (max-width:900px) {
    .block-container { padding-left:1.1rem; padding-right:1.1rem; }
    .tap-stats { grid-template-columns:repeat(2,1fr); }
    .tap-hero { grid-template-columns:1fr; padding:28px 24px; }
    .tap-loop-card { display:none; }
    .tap-report-hero { grid-template-columns:1fr; }
    .tap-project-row { grid-template-columns:1fr .55fr; }
    .tap-project-row > :nth-child(2), .tap-project-row > :nth-child(4) { display:none; }
    .tap-guide-grid { grid-template-columns:repeat(2,1fr); }
    .tap-report-sheet { min-height:0; padding:34px 28px 52px; }
    .tap-report-brand { margin-bottom:58px; }
    .tap-report-watermark { right:28px; top:30px; }
    .tap-report-sheet footer { left:28px; right:28px; bottom:20px; }
    .tap-report-kpis { grid-template-columns:repeat(2,1fr); }
    .tap-report-score-row { grid-template-columns:140px 1fr 42px; }
    .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadio"] [role="radiogroup"] { grid-template-columns:repeat(3,minmax(0,1fr)); }
  }
  @media (max-width:560px) {
    .tap-page-head { display:block; }
    .tap-page-head h1 { font-size:26px; }
    .tap-page-head .tap-chip { margin-top:12px; }
    .tap-stats { grid-template-columns:1fr; }
    .tap-hero h2 { font-size:28px; }
    .stApp [data-testid="stVerticalBlockBorderWrapper"]:has(.tap-question-stage-anchor) { margin:14px auto 24px; padding:20px 15px !important; border-radius:21px !important; }
    .tap-question-panel { padding:28px 0 30px; }
    .tap-question-panel h2 { font-size:23px; line-height:1.45; }
    .tap-response-head { display:block; }
    .tap-response-head span { display:block; margin-top:4px; }
    .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadio"] [role="radiogroup"] { grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
    .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"] { min-height:100px; padding:12px 6px 10px !important; }
    .stApp [data-testid="stForm"]:has(.tap-response-anchor) [data-testid="stRadioOption"]::before { width:36px; height:36px; flex-basis:36px; border-radius:11px; font-size:16px; }
    .tap-guide-grid { grid-template-columns:1fr; }
    .tap-report-meta { display:grid; }
    .tap-report-kpis,.tap-report-method-grid { grid-template-columns:1fr; }
    .tap-report-score-row { grid-template-columns:1fr 42px; }
    .tap-report-score-row>div:first-child { grid-column:1/-1; }
    .tap-report-priority { grid-template-columns:30px 1fr; }
    .tap-report-priority em { grid-column:2; width:max-content; }
  }

  @media print {
    [data-testid="stSidebar"], [data-testid="stHeader"], .stDownloadButton, .stButton, [data-testid="stFileUploader"], .tap-page-head { display:none !important; }
    .stApp,.block-container { background:#fff !important; max-width:none !important; padding:0 !important; }
    .tap-report-document { display:block; margin:0; }
    .tap-report-sheet { width:210mm; min-height:297mm; margin:0; padding:17mm 16mm 16mm; border:0; border-radius:0; box-shadow:none; page-break-after:always; }
    .tap-report-sheet:last-child { page-break-after:auto; }
    .tap-report-sheet footer { left:16mm; right:16mm; bottom:10mm; }
  }
</style>
"""


def setup_page(page_title: str, page_icon: str = "T") -> str:
    st.set_page_config(
        page_title=f"{page_title} | TAP",
        page_icon=page_icon,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(MOCKUP_CSS, unsafe_allow_html=True)
    return _render_sidebar()


def _safe_page_link(path: str, label: str, *, key: str) -> None:
    """Keep the app usable when Streamlit Cloud has a stale page registry."""
    try:
        st.page_link(path, label=label, use_container_width=True)
    except StreamlitPageNotFoundError:
        _missing_page_button(label, key=key)
    except KeyError as exc:
        if exc.args != ("url_pathname",):
            raise
        _missing_page_button(label, key=key)


def _missing_page_button(label: str, *, key: str) -> None:
    st.button(
        f"{label} · 준비 중",
        key=key,
        disabled=True,
        help="배포 페이지 등록을 갱신하고 있습니다. 잠시 후 다시 시도해 주세요.",
        width="stretch",
    )


def safe_switch_page(path: str) -> bool:
    """Switch pages without turning a stale Cloud registry into an app crash."""
    try:
        st.switch_page(path)
    except (StreamlitAPIException, StreamlitPageNotFoundError):
        st.error("화면 연결을 갱신하고 있습니다. 잠시 후 다시 눌러 주세요.")
        return False
    except KeyError as exc:
        if exc.args != ("url_pathname",):
            raise
        st.error("화면 연결을 갱신하고 있습니다. 잠시 후 다시 눌러 주세요.")
        return False
    return True


def _render_sidebar() -> str:
    # Apply a role requested by a CTA before drawing the destination sidebar.
    query_role = st.query_params.get("tap_role")
    if query_role in ROLE_LABELS:
        st.session_state.active_role = query_role

    pending_role = st.session_state.pop("tap_pending_role", None)
    if pending_role in ROLE_LABELS:
        st.session_state.active_role = pending_role

    if "active_role" not in st.session_state:
        st.session_state.active_role = "company"
    active_role = str(st.session_state.active_role)
    if active_role not in ROLE_LABELS:
        active_role = "company"
        st.session_state.active_role = active_role

    with st.sidebar:
        st.markdown(
            """
            <div class="tap-brand">
              <div class="tap-brandmark">TAP</div>
              <div><strong>KMA TAP</strong><small>교육수요·업무행동 점검</small></div>
            </div>
            <div class="tap-beta">회원사 전용 BETA · 공개 데모</div>
            <div class="tap-side-label">역할 전환</div>
            """,
            unsafe_allow_html=True,
        )
        requested_role: str | None = None
        for role, label in ROLE_LABELS.items():
            if st.button(
                label,
                key=f"tap_role_{role}",
                type="primary" if role == active_role else "secondary",
                width="stretch",
            ):
                requested_role = role

        if requested_role is not None and requested_role != active_role:
            previous_role = active_role
            st.session_state.active_role = requested_role
            if not safe_switch_page(ROLE_LANDINGS[requested_role]):
                st.session_state.active_role = previous_role

        selected_role = str(st.session_state.active_role)

        st.markdown('<div class="tap-side-label">메뉴</div>', unsafe_allow_html=True)
        for index, (path, label) in enumerate(ROLE_NAV[selected_role]):
            _safe_page_link(
                path,
                label,
                key=f"tap_missing_nav_{selected_role}_{index}",
            )

        guide_path = Path(PROJECT_ROOT) / "docs" / "TAP_사용설명서_v3.pdf"
        if guide_path.exists():
            st.download_button(
                "사용설명서",
                guide_path.read_bytes(),
                guide_path.name,
                "application/pdf",
                key=f"tap_sidebar_guide_{selected_role}",
                width="stretch",
            )

        notes = {
            "company": (
                "회원사 교육담당자 화면",
                "교육 일정과 사전·사후 참여율을 운영하고 전·후 유효응답 N≥5 조직 변화를 확인합니다.",
            ),
            "participant": (
                "참여자 교육평가 화면",
                "본인의 사전·사후 검사와 변화 리포트만 확인합니다. 결과 공유 동의는 선택입니다.",
            ),
            "kma": (
                "KMA 관리자 화면",
                "회원사 운영상태·문항 버전·과정 매핑·감사로그만 관리합니다.",
            ),
        }
        title, body = notes[selected_role]
        st.markdown(
            f'<div class="tap-side-note"><b>{escape(title)}</b>{escape(body)}</div>',
            unsafe_allow_html=True,
        )
        st.caption("DEMO MODE · 개인식별정보를 입력하지 마세요.")
    return selected_role


def switch_role_page(role: str, path: str) -> None:
    """Switch pages and synchronize the persistent role on the destination run."""
    if role not in ROLE_LABELS:
        raise ValueError(f"Unknown TAP role: {role}")
    st.session_state.tap_pending_role = role
    if not safe_switch_page(path):
        st.session_state.pop("tap_pending_role", None)


def page_header(
    eyebrow: str,
    title: str,
    description: str,
    *,
    badge: str | None = None,
    badge_tone: str = "teal",
) -> None:
    badge_html = (
        f'<span class="tap-chip {escape(badge_tone)}">{escape(badge)}</span>' if badge else ""
    )
    st.markdown(
        f"""
        <div class="tap-page-head">
          <div>
            <div class="tap-eyebrow">{escape(eyebrow)}</div>
            <h1>{escape(title)}</h1>
            <p>{escape(description)}</p>
          </div>
          {badge_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def dashboard_hero() -> None:
    st.markdown(
        """
        <section class="tap-hero">
          <div class="tap-hero-copy">
            <span class="tap-chip teal">교육 전후 역량평가 · 회원사 제공</span>
            <h2>교육 전후의 변화를<br>같은 기준으로 확인합니다.</h2>
            <p>교육 전 출발점을 기록하고, 교육 후 현업 적용 시점에 같은 행동문항으로 다시 측정해 개인·조직의 관찰된 변화와 현업 적용환경을 확인합니다.</p>
          </div>
          <div class="tap-loop-card">
            <div class="tap-loop-step"><span>1</span>사전검사</div>
            <div class="tap-loop-arrow"></div>
            <div class="tap-loop-step"><span>2</span>교육·현업 적용</div>
            <div class="tap-loop-arrow"></div>
            <div class="tap-loop-step"><span>3</span>사후검사</div>
            <div class="tap-loop-arrow"></div>
            <div class="tap-loop-step"><span>4</span>변화·전이 리포트</div>
          </div>
        </section>
        """,
        unsafe_allow_html=True,
    )


def metric_grid(metrics: Sequence[Mapping[str, object]]) -> None:
    cards = []
    for metric in metrics:
        cards.append(
            "".join(
                (
                    '<div class="tap-stat">',
                    f'<b>{escape(str(metric["value"]))}</b>',
                    f'<span>{escape(str(metric["label"]))}</span>',
                    f'<small>{escape(str(metric.get("note", "")))}</small>',
                    "</div>",
                )
            )
        )
    st.markdown(f'<div class="tap-stats">{"".join(cards)}</div>', unsafe_allow_html=True)


def callout(title: str, body: str, *, icon: str = "✓", tone: str = "info") -> None:
    tone_class = "" if tone == "info" else escape(tone)
    st.markdown(
        f"""
        <div class="tap-callout {tone_class}">
          <div class="tap-callout-icon">{escape(icon)}</div>
          <div><strong>{escape(title)}</strong><br>{escape(body)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def project_rows(projects: Iterable[Mapping[str, object]]) -> None:
    rows = []
    tone_by_status = {"진행 중": "teal", "준비": "amber", "완료": "", "주의": "coral"}
    for project in projects:
        completion = max(0, min(100, int(project["completion_pct"])))
        status = str(project["status"])
        tone = tone_by_status.get(status, "")
        rows.append(
            f"""
            <div class="tap-project-row">
              <div><b>{escape(str(project['name']))}</b><small>{escape(str(project['scope']))}</small></div>
              <div><div class="tap-progress"><i style="width:{completion}%"></i></div><small>{completion}%</small></div>
              <div class="tap-project-metric">{escape(str(project['completed']))} / {escape(str(project['invited']))}</div>
              <span class="tap-chip {tone}">{escape(status)}</span>
            </div>
            """
        )
    st.markdown("".join(rows), unsafe_allow_html=True)


def summary_strip(items: Sequence[tuple[str, str]]) -> None:
    html = "".join(
        f'<div class="tap-summary-item"><b>{escape(value)}</b><span>{escape(label)}</span></div>'
        for value, label in items
    )
    st.markdown(f'<div class="tap-summary-strip">{html}</div>', unsafe_allow_html=True)


def domain_header(title: str, detail: str) -> None:
    st.markdown(
        f'<div class="tap-domain-head"><b>{escape(title)}</b><span>{escape(detail)}</span></div>',
        unsafe_allow_html=True,
    )
