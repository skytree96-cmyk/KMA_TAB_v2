"""Customer-facing guide for education managers and participants.

Screens are drawn as static HTML mockups with numbered pins so the guide never
shows real accounts or responses and stays readable when the live UI changes.
KMA administrator workflows are intentionally excluded.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Iterable

import streamlit as st

from tap.account_navigation import switch_to_page
from tap.account_theme import account_theme_css
from tap.brand import brand_css, brand_html


GUIDE_CSS = """
<style>
  .tg-intro{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:4px 0 8px}
  .tg-intro div{background:#fff;border:1px solid #dce9e6;border-radius:14px;padding:16px 18px}
  .tg-intro b{display:block;color:#087b76;font-size:13px;letter-spacing:.04em;margin-bottom:4px}
  .tg-intro strong{display:block;color:#102f36;font-size:17px;margin-bottom:6px}
  .tg-intro p{margin:0;color:#536f75;font-size:14px;line-height:1.6}
  .tg-flow{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:6px 0 18px;font-size:14px;color:#102f36}
  .tg-flow span{background:#eaf6f3;color:#087b76;border-radius:999px;padding:6px 12px;font-weight:700}
  .tg-flow em{font-style:normal;color:#9db1b3}
  .tg-step{display:grid;grid-template-columns:minmax(0,1.15fr) minmax(0,1fr);gap:26px;align-items:start;
           padding:24px;border:1px solid #dce9e6;border-radius:18px;background:#fff;margin:0 0 18px;color:#102f36}
  .tg-head{grid-column:1/-1}
  .tg-kicker{font-size:13px;font-weight:800;color:#087b76;letter-spacing:.05em}
  .tg-head h3{margin:4px 0 6px;font-size:22px;line-height:1.35;color:#102f36}
  .tg-lead{color:#536f75;font-size:15px;line-height:1.65;margin:0}
  .tg-frame{border:1px solid #d5e2e0;border-radius:14px;overflow:hidden;background:#f4f8f8;box-shadow:0 10px 28px rgba(16,47,54,.08)}
  .tg-bar{display:flex;align-items:center;gap:6px;padding:8px 12px;background:#e7efee;font-size:11px;color:#7a8f93}
  .tg-bar i{width:9px;height:9px;border-radius:50%;background:#c5d4d2;display:inline-block}
  .tg-bar span{margin-left:8px}
  .tg-screen{padding:16px;display:flex;flex-direction:column;gap:10px;font-size:13px;color:#102f36}
  .tg-pin{display:inline-flex;align-items:center;justify-content:center;width:20px;height:20px;border-radius:50%;
          background:#e8590c;color:#fff;font-size:11px;font-weight:800;flex:none;box-shadow:0 0 0 3px rgba(232,89,12,.2)}
  .tg-pinned{position:relative;display:inline-flex;margin:6px 8px 0 0}
  .tg-pinned.full{display:flex;width:100%;margin-right:0}
  .tg-pinned > .tg-pin{position:absolute;top:-9px;right:-9px;width:19px;height:19px;font-size:10.5px;z-index:1}
  .tg-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:7px 12px;border-radius:8px;
          font-weight:700;font-size:12.5px;border:1px solid #087b76;white-space:nowrap}
  .tg-btn.primary{background:#087b76;color:#fff}
  .tg-btn.secondary{background:#fff;color:#087b76}
  .tg-btn.ghost{border-color:transparent;background:transparent;color:#536f75}
  .tg-btn.active{background:#087b76;color:#fff}
  .tg-btn.full{width:100%;box-sizing:border-box}
  .tg-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
  .tg-row > .tg-field{flex:1}
  .tg-field{display:flex;flex-direction:column;gap:4px;min-width:110px}
  .tg-field b{font-size:11.5px;color:#536f75;font-weight:600;display:flex;align-items:center;gap:6px}
  .tg-input{background:#fff;border:1px solid #d5e2e0;border-radius:7px;padding:7px 9px;color:#102f36;min-height:16px}
  .tg-input.ph{color:#9db1b3}
  .tg-card{background:#fff;border:1px solid #dce9e6;border-radius:10px;padding:12px;display:flex;flex-direction:column;gap:8px}
  .tg-title{font-weight:800;font-size:15px}
  .tg-sub{font-size:11.5px;color:#6b8589}
  .tg-table{width:100%;border-collapse:collapse;background:#fff;font-size:11.5px;border-radius:8px;overflow:hidden}
  .tg-table th{background:#eef5f4;color:#536f75;text-align:left;padding:6px 8px;font-weight:600}
  .tg-table td{border-top:1px solid #e6eeed;padding:6px 8px}
  .tg-tag{display:inline-block;padding:3px 8px;border-radius:999px;background:#eaf6f3;color:#087b76;font-size:11px;font-weight:700}
  .tg-tag.muted{background:#f1f4f5;color:#7a8f93}
  .tg-metric{flex:1;min-width:84px;background:#fff;border:1px solid #dce9e6;border-radius:10px;padding:9px 10px}
  .tg-metric small{display:block;color:#6b8589;font-size:11px}
  .tg-metric strong{font-size:17px}
  .tg-progress{height:7px;background:#e3ecea;border-radius:99px;overflow:hidden;flex:1}
  .tg-progress span{display:block;height:100%;background:#087b76}
  .tg-radio{display:flex;flex-wrap:wrap;gap:6px}
  .tg-radio span{border:1px solid #d5e2e0;background:#fff;border-radius:99px;padding:4px 9px;font-size:11.5px}
  .tg-radio span.on{border-color:#087b76;background:#eaf6f3;color:#087b76;font-weight:700}
  .tg-scale{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));width:100%}
  .tg-scale span{display:flex;align-items:center;justify-content:center;text-align:center;min-height:34px;padding:4px 3px;
                 margin-left:-1px;border:1px solid #b9cccb;background:#f4f7f7;font-size:11px;font-weight:600;color:#33484f;word-break:keep-all}
  .tg-scale span:first-child{margin-left:0;border-radius:9px 0 0 9px}
  .tg-scale span:last-child{border-radius:0 9px 9px 0}
  .tg-scale span.hover{background:#dff2ee;border-color:#7cc4ba;color:#065c58;position:relative;z-index:1}
  .tg-scale span.on{background:#087b76;border-color:#087b76;color:#fff;font-weight:800;position:relative;z-index:2}
  .tg-zero{align-self:flex-start;border:1px dashed #b9cccb;border-radius:999px;background:#fff;padding:5px 12px;font-size:11px;font-weight:600;color:#33484f}
  .tg-checks{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:11.5px}
  .tg-checks span::before{content:"";display:inline-block;width:11px;height:11px;margin-right:5px;vertical-align:-1px;
                          border:1.5px solid #9db1b3;border-radius:3px;background:#fff}
  .tg-checks span.on::before{background:#087b76;border-color:#087b76;box-shadow:inset 0 0 0 2px #fff}
  .tg-tiles{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}
  .tg-tiles span{border:1px solid #dce9e6;border-radius:8px;background:#fff;padding:6px 8px;font-size:11px}
  .tg-tiles span::before{content:"";display:inline-block;width:10px;height:10px;margin-right:5px;vertical-align:-1px;
                         border:1.5px solid #9db1b3;border-radius:3px}
  .tg-tiles span.on{border-color:#087b76;background:#eaf6f3;font-weight:700}
  .tg-tiles span.on::before{background:#087b76;border-color:#087b76}
  .tg-tiles span.fixed{color:#6b8589}
  .tg-tiles span.fixed::before{background:#c5d4d2;border-color:#c5d4d2}
  .tg-shell{display:grid;grid-template-columns:136px minmax(0,1fr);gap:8px;background:#e6eaeb;border-radius:10px;padding:6px 6px 6px 0}
  .tg-side{display:flex;flex-direction:column;gap:2px;min-height:170px;padding:10px 6px 8px 8px;border-radius:0 10px 10px 0;
           background:linear-gradient(165deg,#d2e6e3 0%,#e3eceb 45%,#eef1f2 100%)}
  .tg-logo{font-weight:900;color:#192c48;font-size:14px;padding:0 4px}
  .tg-logo em{font-style:normal;color:#087f83}
  .tg-who{margin:6px 0 4px;padding:6px 8px;border-radius:8px;background:rgba(255,255,255,.6);font-size:10.5px;color:#5e6a76;line-height:1.35}
  .tg-who b{display:block;color:#111a24;font-size:11px}
  .tg-side .tg-btn{justify-content:flex-start;width:100%;box-sizing:border-box;border-radius:999px;border-color:transparent;
                   background:transparent;color:#333e4a;font-weight:600;padding:6px 9px}
  .tg-side .tg-btn.active{background:#fff;color:#111a24;font-weight:800;box-shadow:0 1px 2px rgba(17,26,36,.08),0 2px 6px rgba(17,26,36,.05)}
  .tg-side .tg-pinned{display:flex;margin:4px 0 0}
  .tg-side-bot{margin-top:auto;padding-top:6px;border-top:1px solid rgba(17,26,36,.1);display:flex;flex-direction:column;gap:2px}
  .tg-main{background:#fff;border-radius:10px;padding:10px;display:flex;flex-direction:column;gap:8px;min-width:0}
  .tg-checks.col{flex-direction:column;gap:6px}
  .tg-upload{border:1.5px dashed #b9cfcc;border-radius:9px;padding:12px;text-align:center;color:#6b8589;background:#fff}
  .tg-exp{border:1px solid #dce9e6;border-radius:10px;background:#fff}
  .tg-exp > .tg-exp-head{padding:9px 12px;font-weight:700;display:flex;gap:8px;align-items:center}
  .tg-exp > .tg-exp-body{border-top:1px solid #e6eeed;padding:12px;display:flex;flex-direction:column;gap:10px}
  .tg-split{display:grid;grid-template-columns:1.2fr 1fr;gap:10px}
  .tg-list-item{padding:8px 10px;border-radius:8px;border:1px solid #e6eeed;background:#fff}
  .tg-list-item.on{border-color:#087b76;background:#eaf6f3}
  .tg-bars{display:flex;flex-direction:column;gap:6px}
  .tg-bars div{display:grid;grid-template-columns:76px 1fr;gap:8px;align-items:center;font-size:11px;color:#536f75}
  .tg-bars p{margin:0;display:flex;flex-direction:column;gap:2px}
  .tg-bars i{display:block;height:6px;border-radius:99px;background:#b9d9d4}
  .tg-bars i.after{background:#087b76}
  .tg-ring{width:64px;height:64px;border-radius:50%;flex:none;
           background:conic-gradient(#087b76 0 62%,#e3ecea 62% 100%);display:flex;align-items:center;justify-content:center}
  .tg-ring span{width:46px;height:46px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:12px}
  .tg-trend{display:flex;align-items:flex-end;gap:5px;height:46px}
  .tg-trend i{flex:1;background:#b9d9d4;border-radius:3px 3px 0 0}
  .tg-trend i.post{background:#087b76}
  .tg-callouts{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:14px}
  .tg-callouts li{display:grid;grid-template-columns:24px 1fr;gap:10px;align-items:start}
  .tg-callouts strong{display:block;color:#102f36;font-size:15px;line-height:1.4}
  .tg-callouts p{margin:3px 0 0;color:#536f75;font-size:14px;line-height:1.6}
  .tg-note{grid-column:1/-1;border-radius:10px;padding:11px 14px;font-size:14px;line-height:1.6;
           background:#eef7f6;border:1px solid #cfe6e2;color:#145049}
  .tg-note.warn{background:#fff8f1;border-color:#f6d7bd;color:#7a3e0d}
  .tg-sec{display:flex;gap:8px;align-items:center;font-weight:800;font-size:13px}
  .tg-sec i{width:22px;height:22px;border-radius:7px;background:#eaf6f3;color:#087b76;display:inline-grid;place-items:center;font-style:normal;font-size:12px}
  .tg-mini{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px}
  .tg-mini span{border:1px solid #dce9e6;border-radius:8px;background:#fff;padding:0 0 6px;font-size:11px;overflow:hidden}
  .tg-mini span i{display:block;height:28px;background:linear-gradient(135deg,#e2ecea,#c9dedb);margin-bottom:5px}
  .tg-mini span b{display:block;padding:0 7px;font-size:11px}
  .tg-mini span em{display:block;padding:0 7px;font-style:normal;color:#6b8589;font-size:10.5px}
  .tg-faq{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin:0 0 8px}
  .tg-faq div{background:#fff;border:1px solid #dce9e6;border-radius:14px;padding:14px 16px;color:#102f36}
  .tg-faq strong{display:block;font-size:15px;margin-bottom:4px}
  .tg-faq p{margin:0;color:#536f75;font-size:14px;line-height:1.6}
  @media(max-width:900px){
    .tg-step{grid-template-columns:1fr;padding:18px;gap:18px}
    .tg-intro,.tg-faq{grid-template-columns:1fr}
    .tg-split{grid-template-columns:1fr}
    .tg-shell{grid-template-columns:1fr;padding:6px}
    .tg-side{min-height:0;border-radius:10px}
  }
</style>
"""


# ---------------------------------------------------------------- primitives

def _pin(number: int | None) -> str:
    return f'<span class="tg-pin">{number}</span>' if number else ""


def _btn(label: str, kind: str = "primary", pin: int | None = None, full: bool = False) -> str:
    classes = f"tg-btn {kind}" + (" full" if full else "")
    button = f'<span class="{classes}">{label}</span>'
    if not pin:
        return button
    return f'<span class="tg-pinned{" full" if full else ""}">{button}{_pin(pin)}</span>'


def _field(label: str, value: str = "", pin: int | None = None, placeholder: bool = False) -> str:
    cls = "tg-input ph" if placeholder else "tg-input"
    return f'<div class="tg-field"><b>{_pin(pin)}{label}</b><div class="{cls}">{value}</div></div>'


def _frame(title: str, body: str) -> str:
    return (f'<div class="tg-frame"><div class="tg-bar"><i></i><i></i><i></i><span>{title}</span></div>'
            f'<div class="tg-screen">{body}</div></div>')


def _table(headers: Iterable[str], rows: Iterable[Iterable[str]]) -> str:
    head = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
    return f'<table class="tg-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _step(kicker: str, title: str, lead: str, mock: str,
          callouts: Iterable[tuple[str, str]], note: str = "", warn: bool = False) -> str:
    items = "".join(
        f'<li>{_pin(index)}<div><strong>{name}</strong><p>{text}</p></div></li>'
        for index, (name, text) in enumerate(callouts, start=1)
    )
    note_html = f'<div class="tg-note{" warn" if warn else ""}">{note}</div>' if note else ""
    return (f'<section class="tg-step"><div class="tg-head"><div class="tg-kicker">{kicker}</div>'
            f'<h3>{title}</h3><p class="tg-lead">{lead}</p></div>'
            f'{mock}<ol class="tg-callouts">{items}</ol>{note_html}</section>')


def _sidebar(menus: Iterable[str], active: str, role: str, body: str, pins: bool = True) -> str:
    """The signed-in frame: left menu (as in assets/console-v2.css) beside the work sheet."""
    menus = list(menus)
    buttons = "".join(
        _btn(menu, "active" if menu == active else "ghost", pin=index if pins else None)
        for index, menu in enumerate(menus, start=1)
    )
    guide = _btn("? 이용 안내", "ghost", pin=len(menus) + 1 if pins else None)
    profile = _btn(f"👤 {role} ▾", "ghost", pin=len(menus) + 2 if pins else None)
    return (f'<div class="tg-shell"><div class="tg-side"><span class="tg-logo">KMA <em>TAP</em></span>'
            f'<div class="tg-who"><b>㈜샘플기업</b>{role}</div>{buttons}'
            f'<div class="tg-side-bot">{guide}{profile}</div></div><div class="tg-main">{body}</div></div>')


MANAGER_MENUS = ("대시보드", "참여자 계정", "프로젝트 만들기", "프로젝트")
SAMPLE_PROJECT = "고객 서비스 역량 향상 과정"


# ---------------------------------------------------------------- shared intro

def _intro() -> str:
    return """
<div class="tg-intro">
  <div><b>STEP 1</b><strong>로그인</strong>
    <p>담당자에게 전달받은 <b style="display:inline;color:#102f36">로그인 ID 전체</b>와 임시 비밀번호를 입력하세요. 이메일은 쓰지 않습니다.</p></div>
  <div><b>STEP 2</b><strong>비밀번호 설정</strong>
    <p>처음 로그인하면 본인만 아는 새 비밀번호(3~128자)를 정해야 다음 화면으로 넘어갈 수 있습니다.</p></div>
  <div><b>STEP 3</b><strong>메뉴로 이동</strong>
    <p>왼쪽 메뉴로 화면을 이동하세요. 메뉴 아래 <b style="display:inline;color:#102f36">이용 안내</b>로 이 화면을 열 수 있고, 프로필에서 비밀번호 변경과 로그아웃을 합니다.</p></div>
</div>
"""


# ---------------------------------------------------------------- manager tab

def _manager_steps() -> list[str]:
    steps = []

    steps.append(_step(
        "화면 구성", "메뉴 구성",
        "교육담당자로 로그인하면 왼쪽에 메뉴 4개가 보입니다. 처음에는 참여자 계정, 프로젝트 만들기, "
        "프로젝트(배정) 순서로 쓰고, 이후에는 대시보드에서 현황을 봅니다.",
        _frame("교육담당자 화면", _sidebar(MANAGER_MENUS, "참여자 계정", "교육담당자",
               '<div class="tg-card"><div class="tg-title">참여자 계정</div>'
               '<div class="tg-sub">선택한 메뉴의 업무 화면이 이 영역에 표시됩니다.</div></div>')),
        [
            ("대시보드", "전체 참여 인원, 교육 전후 검사 완료 현황, 일정과 미완료 인원, 월별 완료 추세"),
            ("참여자 계정", "참여자 계정 발급(한 명씩 또는 CSV 일괄), 비밀번호 재발급, 사용 중지"),
            ("프로젝트 만들기", "교육 일정과 측정역량을 정해 새 프로젝트 등록"),
            ("프로젝트", "프로젝트별 일정, 참여자 배정, 참여 현황과 리포트"),
            ("이용 안내", "이 안내 화면 열기. <b>업무 화면으로 돌아가기</b>를 누르면 보던 화면으로 복귀"),
            ("프로필 (교육담당자 ▾)", "내 이름·아이디·회사 표시, 비밀번호 변경, 로그아웃"),
        ],
    ))

    steps.append(_step(
        "STEP 1 · 참여자 계정 메뉴", "참여자 계정 발급하기",
        "검사에 참여할 직원 계정부터 만드세요. 인원이 적으면 한 명씩, 많으면 CSV로 한꺼번에 등록하세요.",
        _frame("참여자 계정", (
            '<div class="tg-exp"><div class="tg-exp-head">▾ 참여자 계정 발급</div><div class="tg-exp-body">'
            '<div class="tg-row">' + _field("아이디", "user001", pin=1) + _field("이름", "홍길동") + '</div>'
            '<div class="tg-row">' + _field("부서", "고객서비스팀") + _field("직급", "주임") + '</div>'
            '<div class="tg-row">' + _field("이메일", "예: name@example.com", placeholder=True) +
            _field("연락처", "예: 010-1234-5678", placeholder=True) + '</div>'
            + _btn("참여자 계정 발급", pin=2) + '</div></div>'
            '<div class="tg-exp"><div class="tg-exp-head">▾ CSV로 참여자 일괄 등록</div><div class="tg-exp-body">'
            + _btn("CSV 양식 내려받기", "secondary", pin=3) +
            '<div class="tg-row">' + _pin(4) + '<div class="tg-upload" style="flex:1">참여자 CSV 파일을 끌어다 놓거나 선택</div></div>'
            + _btn("새 참여자 12명 등록", pin=5) + '</div></div>'
        )),
        [
            ("아이디 정하기", "영문 소문자, 숫자, 점(.), 밑줄(_), 하이픈(-)으로 3~64자. <b>user001</b>처럼 user 뒤에 숫자만 붙인 "
             "기본 아이디는 앞에 회사 식별정보가 붙음(예: 1234567890-user001). 직접 정한 아이디는 입력한 대로 사용됨"),
            ("참여자 계정 발급", "이름은 필수이고 부서, 직급, 이메일, 연락처는 선택. 부서와 직급은 배정할 때 검색에 쓰이고, 부서는 부서 전체 선택에도 쓰임"),
            ("CSV 양식 내려받기", "아이디, 이름, 부서, 직급, 이메일, 연락처 열이 들어 있는 양식. 엑셀에서 작성한 뒤 ‘CSV UTF-8(쉼표로 분리)’ 형식으로 저장"),
            ("CSV 올리기", "저장한 CSV를 올리면 등록할 목록이 먼저 보임. 이미 있는 아이디는 <b>기존 계정 · 제외</b>로 표시되고 변경되지 않음. 한 번에 최대 200명"),
            ("새 참여자 N명 등록", "목록을 본 뒤 눌러야 계정이 생성됨. 한 행이라도 실패하면 아무 계정도 등록되지 않으니, 표시된 아이디를 고쳐 다시 올림"),
        ],
    ))

    steps.append(_step(
        "STEP 2 · 참여자 계정 메뉴", "로그인 정보 전달과 계정 관리",
        "계정을 발급하면 화면 상단에 <b>발급한 로그인 정보</b>가 표시됩니다. 이 정보를 참여자에게 전달하세요.",
        _frame("참여자 계정", (
            '<div class="tg-card"><div class="tg-title">발급한 로그인 정보</div>' +
            _table(("로그인 아이디", "이름", "임시 비밀번호"),
                   (("1234567890-user001", "홍길동", "••••"), ("1234567890-user002", "김하나", "••••"))) +
            '<div class="tg-row">' + _btn("로그인 정보 CSV 내려받기", "secondary", pin=1) +
            _btn("전달 완료 · 발급 정보 닫기", "ghost", pin=2) + '</div></div>'
            '<div class="tg-split"><div class="tg-card"><div class="tg-row">' + _pin(5) + '<span class="tg-sub">계정 목록 · 가나다순</span></div>'
            '<div class="tg-radio"><span class="on">전체 42</span><span>ㄱ~ㅁ 14</span><span>ㅂ~ㅇ 15</span><span>ㅈ~ㅎ 13</span></div>'
            '<div class="tg-list-item">김하나 · user002</div><div class="tg-list-item on">홍길동 · user001</div>'
            '<div class="tg-sub">42명 중 1~10 · 1 / 5 페이지</div></div>'
            '<div class="tg-card"><div class="tg-sub">계정 상세</div><div class="tg-title">홍길동</div>' +
            _btn("임시 비밀번호 재발급", "secondary", pin=3) + _btn("계정 사용 중지", "ghost", pin=4) + '</div></div>'
        )),
        [
            ("로그인 정보 CSV 내려받기", "아이디·이름·임시 비밀번호가 담긴 파일. 참여자 안내 메일이나 메신저 발송용"),
            ("전달 완료 · 발급 정보 닫기", "전달을 마친 뒤 눌러서 화면에서 지움. 닫으면 임시 비밀번호를 다시 볼 수 없음"),
            ("임시 비밀번호 재발급", "비밀번호를 잊은 참여자에게 새 임시 비밀번호 발급. 기존 로그인은 종료됨"),
            ("계정 사용 중지", "퇴사·대상 제외 등으로 로그인을 막아야 하는 계정에 사용. 다시 활성화할 수 있고, 기존 검사 결과는 남음"),
            ("계정 목록", "가나다순으로 10명씩 보임. 10명이 넘으면 <b>전체</b>와 초성 구간(예: ㄱ~ㅁ)으로 나뉘고, 이름, 아이디, 부서로 검색 가능. "
             "여러 명은 아래 <b>여러 계정 한 번에 처리</b>에서 체크해 한꺼번에 재발급하거나 사용 중지"),
        ],
        note="임시 비밀번호는 <b>발급 직후 이 화면에서만</b> 볼 수 있습니다. CSV로 내려받거나 따로 기록한 뒤 닫으세요.",
        warn=True,
    ))

    steps.append(_step(
        "STEP 3 · 프로젝트 만들기 메뉴", "교육평가 프로젝트 만들기",
        "교육 1건(또는 차수 1개)마다 프로젝트를 하나 만드세요. 여기서 정한 측정역량과 검사 기간이 참여자 화면에도 적용됩니다.",
        _frame("프로젝트 만들기", (
            '<div class="tg-field"><b>' + _pin(1) + '응답 대상</b><div class="tg-radio">'
            '<span class="on">실무자</span><span>관리자·리더</span><span>임원</span></div></div>'
            '<div class="tg-field"><b>' + _pin(2) + '측정역량</b>'
            '<div class="tg-sub">기본역량 · 자동 포함</div><div class="tg-tiles">'
            '<span class="fixed">고객지향</span><span class="fixed">협업과 팀워크</span><span class="fixed">문제해결력</span></div>'
            '<div class="tg-sub">전문·미래역량 · 1/3 선택</div><div class="tg-tiles">'
            '<span class="on">AI 도구 활용</span><span>변화 대응</span><span>데이터 기반 판단</span></div>'
            '<div class="tg-sub">측정역량 8개 · 문항 32개</div></div>'
            '<div class="tg-row">' + _field("프로젝트명", "2026 하반기 CS 역량 과정", pin=3) + _field("교육과정명", SAMPLE_PROJECT) + '</div>'
            '<div class="tg-row">' + _field("교육일", "2026-11-12") + _field("교육 전 검사", "11-01 ~ 11-10", pin=4) +
            _field("교육 후 검사", "2027-01-11 ~ 01-18") + '</div>'
            '<div class="tg-row">' + _field("조직 기대 행동빈도", "3.5", pin=5) + _field("조직 우선역량", "고객지향") +
            _field("선호 교육방식", "무관") + '</div>' + _btn("프로젝트 등록", pin=6, full=True)
        )),
        [
            ("응답 대상", "실무자 / 관리자·리더 / 임원 중 선택. 대상에 따라 고를 수 있는 역량이 달라짐"),
            ("측정역량", "기본역량은 자동 포함. 체크박스로 <b>전문·미래역량 최대 3개</b>, <b>직무역량 최대 1개</b> 선택. 한도를 채우면 나머지는 잠기고, 아래에 총 문항 수가 표시됨. 역량에 마우스를 올리면 정의가 보임"),
            ("프로젝트명 · 교육과정명", "참여자 화면과 리포트에 표시되므로 참여자가 알아보기 쉬운 이름으로 입력"),
            ("교육일 · 검사 기간", "교육 전 검사는 교육일까지 끝나도록, 교육 후 검사는 <b>교육 8~10주 후</b>에 시작하도록 설정 권장. 기간 밖에는 참여자가 응답할 수 없음"),
            ("조직 기대치 · 우선역량 · 교육방식", "조직 기대 행동빈도는 리포트에서 목표 대비 차이를 보는 기준. 조직 우선역량(최대 3개)과 선호 교육방식은 리포트의 교육과정 추천 순서에 반영됨"),
            ("프로젝트 등록", "누르면 프로젝트 생성. 다음 단계에서 참여자 배정"),
        ],
        note="<b>등록 후에는 측정역량과 문항을 바꿀 수 없습니다.</b> 교육 전후를 같은 기준으로 비교하기 위해서입니다.",
        warn=True,
    ))

    steps.append(_step(
        "STEP 4 · 프로젝트 메뉴", "참여자 배정하기",
        "왼쪽에서 프로젝트를 고르면 오른쪽에 일정이 보이고, 그 아래에 <b>참여자 배정</b>이 화면 전체 폭으로 열립니다. 배정된 참여자만 내 교육 화면에서 이 교육을 볼 수 있습니다.",
        _frame("프로젝트", (
            '<div class="tg-split"><div class="tg-card">' + _field("프로젝트 검색", "회사명, 사업자등록번호, 프로젝트명, 교육명으로 검색", pin=1, placeholder=True) +
            f'<div class="tg-list-item on">2026 하반기 CS 역량 과정<div class="tg-sub">{SAMPLE_PROJECT}</div></div>'
            '<div class="tg-list-item">리더십 기본 과정<div class="tg-sub">신임 팀장 교육</div></div></div>'
            '<div class="tg-card"><div class="tg-sub">프로젝트 상세</div><div class="tg-title">2026 하반기 CS 역량 과정</div>'
            '<div class="tg-sub">교육일 2026-11-12<br>교육 전 검사 11-01 ~ 11-10<br>교육 후 검사 2027-01-11 ~ 01-18</div></div></div>'
            '<div class="tg-card"><div class="tg-title">참여자 배정</div>'
            '<div class="tg-row">' + _pin(2) + '<div class="tg-radio"><span class="on">전체 15</span><span>미시작 3</span>'
            '<span>진행 중 2</span><span>교육 전 완료 10</span><span>교육 후 완료 0</span></div></div>'
            '<div class="tg-row">' + _btn("교육 전 미완료자 명단 CSV (5명)", "secondary", pin=3) + '</div>'
            '<div class="tg-exp"><div class="tg-exp-head">▾ 고객서비스팀 · 교육 전 완료 9/14명</div><div class="tg-exp-body">'
            '<div class="tg-radio"><span class="on">전체 14</span><span>ㄱ~ㅇ 8</span><span>ㅈ~ㅎ 6</span></div>' +
            _table(("이름", "부서", "상태", "진행"),
                   (("홍길동", "고객서비스팀", "교육 전 완료", ""), ("김하나", "고객서비스팀", "진행 중", "교육 전 12/24"))) +
            '</div></div>'
            '<div class="tg-row">' + _pin(4) + '<span class="tg-btn ghost">▸ 참여자 배정 변경</span></div>'
            '<b>참여자 추가</b>'
            '<div class="tg-field"><b>' + _pin(5) + '부서 전체 선택</b><div class="tg-radio">'
            '<span class="on">매장운영팀 4</span><span>영업지원팀 3</span></div></div>'
            + _field("추가할 참여자 검색", "이름, 아이디, 부서, 직급으로 검색", placeholder=True) +
            '<div class="tg-radio"><span class="on">전체 24</span><span>ㄱ~ㅂ 9</span><span>ㅅ~ㅇ 8</span><span>ㅈ~ㅎ 7</span></div>'
            + _btn("✓ 이 페이지 10명 모두 선택", "ghost") +
            '<div class="tg-checks col"><span class="on">김하나 · user002 · 영업지원팀</span>'
            '<span class="on">박민수 · user007 · 매장운영팀</span><span>이서연 · user011 · 고객서비스팀</span></div>'
            '<div class="tg-sub">24명 중 1~10 · 1 / 3 페이지</div>'
            '<div class="tg-row">' + _btn("선택한 6명 배정", pin=6) + '</div></div>'
        )),
        [
            ("프로젝트 검색·선택", "회사명, 사업자등록번호, 프로젝트명, 교육명으로 검색. 프로젝트를 고르면 오른쪽에 일정, 그 아래에 참여자 배정과 참여 현황·리포트가 열림"),
            ("검사 상태", "전체, 미시작, 진행 중, 교육 전 완료, 교육 후 완료 중 하나를 누르면 그 상태인 사람만 보임. 부서별로 묶어 완료 인원을 보여 주고, "
             "진행 중이면 응답한 문항 수(예: 교육 전 12/24)가 표시됨. 부서 안에서는 가나다순 10명씩 보이고, 10명이 넘으면 <b>전체</b>와 초성 구간으로 나뉨. "
             "<b>배정된 참여자 검색</b>으로 이름, 아이디, 부서, 직급 검색 가능"),
            ("미완료자 명단 CSV", "교육 후 검사 시작일 전에는 교육 전 검사를, 그 뒤에는 교육 후 검사를 마치지 않은 사람의 명단. "
             "이름, 아이디, 부서, 직급, 상태만 담기며 사내 메신저로 독려할 때 씀"),
            ("참여자 배정 변경", "잘못 배정한 사람은 <b>프로젝트 배정 해제</b>. 해제해도 제출한 검사 결과는 보존되고, 다시 배정할 수 있음"),
            ("부서 전체 선택", "아직 배정하지 않은 우리 회사 참여자를 부서 단위로 한 번에 선택. 부서에 없는 사람은 아래 목록에서 한 명씩 체크하거나 "
             "<b>이 페이지 10명 모두 선택</b>. 목록은 가나다순 10명씩이고 <b>추가할 참여자 검색</b>으로 좁힐 수 있으며, 페이지를 넘겨도 체크가 유지됨. "
             "계정이 없으면 참여자 계정 메뉴에서 먼저 발급"),
            ("선택한 N명 배정", "누르면 배정되고, 참여자가 로그인하면 내 교육 화면에 표시됨"),
        ],
    ))

    steps.append(_step(
        "STEP 5 · 대시보드 메뉴", "운영 현황 보기",
        "검사 기간에는 대시보드에서 참여율과 미완료 인원을 보고 독려 시점을 정하세요.",
        _frame("대시보드", (
            '<div class="tg-row">' + _pin(1) +
            '<div class="tg-metric"><small>검사 참여 인원</small><strong>42 명</strong></div>'
            '<div class="tg-metric"><small>교육 전 검사 완료</small><strong>38 명</strong></div>'
            '<div class="tg-metric"><small>교육 후 검사 완료</small><strong>21 명</strong></div>'
            '<div class="tg-metric"><small>운영 프로젝트</small><strong>3 개</strong></div></div>'
            '<div class="tg-split"><div class="tg-card"><div class="tg-row">' + _pin(2) + '<b>조직 전체 역량검사 참여 현황</b></div>'
            '<div class="tg-row"><div class="tg-ring"><span>62%</span></div><div class="tg-sub">검사 참여율<br>전체 등록 참여자 대비</div></div></div>'
            '<div class="tg-card"><div class="tg-row">' + _pin(3) + '<b>프로젝트별 검사 완료 현황</b></div>'
            '<div class="tg-bars"><div>CS 역량 과정<p><i style="width:90%"></i><i class="after" style="width:55%"></i></p></div>'
            '<div>리더십 과정<p><i style="width:70%"></i><i class="after" style="width:20%"></i></p></div></div></div></div>'
            '<div class="tg-split"><div class="tg-card"><div class="tg-row">' + _pin(4) + '<b>조직 전체 검사 완료 추세</b></div>'
            '<div class="tg-trend"><i style="height:30%"></i><i class="post" style="height:10%"></i><i style="height:80%"></i>'
            '<i class="post" style="height:35%"></i><i style="height:55%"></i><i class="post" style="height:70%"></i></div></div>'
            '<div class="tg-card"><div class="tg-row">' + _pin(5) + '<b>일정·미완료 점검</b></div>'
            '<div class="tg-sub">CS 역량 과정 · 교육 후 검사 진행 · 미완료 9명<br>리더십 과정 · 교육 전 검사 5일 후 시작</div></div></div>'
        )),
        [
            ("요약 카드", "검사 참여 인원(한 문항 이상 저장한 사람), 교육 전후 검사 완료 인원, 운영 중인 프로젝트 수"),
            ("조직 전체 역량검사 참여 현황", "우리 회사에 등록된 전체 참여자 대비 검사 참여율과 교육 전후 검사 완료율, 아직 참여하지 않은 인원. 여러 프로젝트에 참여해도 한 명으로 계산"),
            ("프로젝트별 검사 완료 현황", "프로젝트별 배정 인원 대비 교육 전후 검사 완료 비율"),
            ("조직 전체 검사 완료 추세", "최근 12개월간 월별 검사 완료 인원"),
            ("일정·미완료 점검", "진행 중이거나 마감된 검사의 미완료 인원과 7일 안에 시작하는 일정. 독려 대상을 고를 때 씀. 아래 프로젝트 현황에서 리포트도 열 수 있음"),
        ],
    ))

    steps.append(_step(
        "STEP 6 · 프로젝트 메뉴 또는 대시보드 하단", "교육 전후 리포트 보기",
        "교육 후 검사까지 마친 참여자가 생기면 프로젝트 화면 아래에 리포트가 열립니다. 보고용으로는 PDF로 내려받으세요.",
        _frame("프로젝트 › 리포트", (
            '<div class="tg-card"><div class="tg-sec">' + _pin(1) + '<i>①</i>참여 현황</div><div class="tg-row">'
            '<div class="tg-metric"><small>배정 인원</small><strong>12 명</strong></div>'
            '<div class="tg-metric"><small>교육 전 검사 완료</small><strong>10 명 · 83%</strong></div>'
            '<div class="tg-metric"><small>교육 후 검사 완료</small><strong>8 명 · 67%</strong></div></div></div>'
            '<div class="tg-card"><div class="tg-sec"><i>②</i>개인별 교육 전후 리포트</div><div class="tg-row">' +
            _field("리포트 참여자", "홍길동 · 1234567890-user001", pin=2) + '</div>' + _btn("개인 리포트 PDF 다운로드", pin=3, full=True) + '</div>'
            '<div class="tg-card"><div class="tg-sec">' + _pin(4) + '<i>③</i>조직 교육 전후 리포트</div>'
            + _btn("조직 리포트 PDF 다운로드", pin=5, full=True) +
            '<div class="tg-bars"><div>고객지향<p><i style="width:58%"></i><i class="after" style="width:76%"></i></p></div>'
            '<div>협업과 팀워크<p><i style="width:64%"></i><i class="after" style="width:72%"></i></p></div>'
            '<div>사람 육성<p><i style="width:50%"></i><i class="after" style="width:61%"></i></p></div></div></div>'
            '<div class="tg-card" style="background:#f7f8f9"><div class="tg-sec">' + _pin(6) + '<i>④</i>현업전이 환경</div><div class="tg-row">'
            '<div class="tg-metric"><small>적용 기회</small><strong>4.00 / 5</strong></div>'
            '<div class="tg-metric"><small>상사·리더 지원</small><strong>4.00 / 5</strong></div>'
            '<div class="tg-metric"><small>도구·정보·권한</small><strong style="color:#b86e00">2.40 / 5</strong></div>'
            '<div class="tg-metric"><small>시간·프로세스</small><strong>3.60 / 5</strong></div></div>'
            '<div class="tg-bars"><div>도구·정보·권한 부족<p><i class="after" style="width:75%"></i></p></div>'
            '<div>시간·프로세스 제약<p><i class="after" style="width:38%"></i></p></div></div></div>'
            '<div class="tg-card" style="background:#eef7f6"><div class="tg-sec">' + _pin(7) + '<i>⑤</i>교육과정 검토 우선순위</div>'
            '<div class="tg-sub">01 사람 육성 · 교육 후 2.90점, 목표 3.50점보다 0.60점 낮음</div>'
            '<div class="tg-mini"><span><i></i><b>[강남] 코칭 리더십</b><em>공개교육 · 최신 일정 보기</em></span>'
            '<span><i></i><b>멘탈관리 수업</b><em>이러닝 · 수강 페이지 보기</em></span>'
            '<span><i></i><b>자기관리와 사람관리</b><em>단체교육 문의 · 과정 안내 보기</em></span></div></div>'
            '<div class="tg-row">' + _btn("조직 리포트 상세 CSV", "secondary", pin=8) + '</div>'
        )),
        [
            ("참여 현황", "선택한 프로젝트의 배정 인원, 교육 전후 검사 완료 인원과 비교 가능 인원"),
            ("리포트 참여자", "교육 전후 검사를 모두 마친 참여자 중 한 명 선택. 이름이나 아이디로 검색 가능"),
            ("개인 리포트 PDF 다운로드", "선택한 참여자의 개인별 교육 전후 변화 리포트. 개인 결과이므로 본인 면담 등 정해진 용도로만 사용"),
            ("조직 교육 전후 리포트", "같은 참여자가 같은 문항에 답한 역량별 평균(1~5)의 교육 전후 비교. 표와 막대로 표시되며, 역량별 유효응답이 5명 이상일 때만 공개"),
            ("조직 리포트 PDF 다운로드", "레이더 차트, 역량별 변화와 업무 적용 가이드, 현업전이 환경, 추천 과정을 담은 보고용 PDF. 과정마다 KMA 페이지로 가는 버튼이 있음"),
            ("현업전이 환경", "교육 후 검사에서 답한 적용 기회, 상사 지원, 도구·권한, 시간 여건의 평균과 적용 장애요인. 3.0점 미만인 조건은 주황색으로 표시"),
            ("교육과정 검토 우선순위", "교육 후 평균이 목표보다 0.2점 이상 낮은 역량마다 공개교육, 이러닝, 단체교육 문의 과정 카드. 버튼을 누르면 KMA 과정 페이지가 새 창에 열림"),
            ("조직 리포트 상세 CSV", "역량별 응답 인원, 교육 전후 점수, 목표 대비 차이와 현업전이 환경 집계를 엑셀에서 가공할 수 있는 파일. 개인별 응답은 담기지 않음"),
        ],
        note="개인 응답 보호를 위해 <b>역량별 교육 전후 유효응답이 5명 이상</b>일 때만 조직 평균과 변화량이 공개됩니다. "
             "수행 기회 없음(0) 응답은 점수에서 제외되며, 결과는 자기보고 변화로 교육의 인과효과를 뜻하지 않습니다.",
    ))
    return steps


MANAGER_FAQ = (
    ("참여자가 비밀번호를 잊었어요", "참여자 계정 메뉴에서 해당 참여자를 선택하고 <b>임시 비밀번호 재발급</b>을 누르세요. 기존 비밀번호는 조회할 수 없습니다."),
    ("제 비밀번호를 잊었어요", "교육담당자 계정은 KMA 담당자에게 재발급을 요청해 주세요."),
    ("참여자가 교육이 안 보인다고 해요", "프로젝트 메뉴의 참여자 배정에 그 참여자가 있고 <b>배정 해제</b> 상태가 아닌지 보세요. 계정이 사용 중지 상태이면 로그인부터 되지 않습니다."),
    ("검사 기간을 놓친 참여자가 있어요", "기간이 지나면 참여자 화면에서 응답할 수 없습니다. 일정 조정이 필요하면 KMA 담당자에게 문의해 주세요."),
)


# ---------------------------------------------------------------- participant tab

def _participant_steps() -> list[str]:
    steps = []

    steps.append(_step(
        "STEP 1 · 로그인", "로그인하고 비밀번호 설정하기",
        "교육담당자에게 받은 아이디와 임시 비밀번호로 로그인하세요. 처음 한 번은 새 비밀번호를 정해야 합니다.",
        _frame("tap.kma.or.kr/login", (
            '<div class="tg-split"><div class="tg-card"><div class="tg-title">로그인</div>' +
            _field("로그인 ID", "1234567890-user001", pin=1) + _field("비밀번호", "••••", pin=2) +
            _btn("로그인", pin=3, full=True) + '</div>'
            '<div class="tg-card"><div class="tg-title">처음 사용할 비밀번호 설정</div>' +
            _field("새 비밀번호", "••••••••", pin=4) + _field("새 비밀번호 확인", "••••••••") +
            _btn("비밀번호 저장", pin=5, full=True) + '</div></div>'
        )),
        [
            ("로그인 ID", "받은 아이디를 <b>앞부분까지 전부</b> 입력(예: 1234567890-user001)"),
            ("비밀번호", "처음에는 교육담당자가 알려준 임시 비밀번호 입력"),
            ("로그인", "로그인하면 비밀번호 설정 화면이 열림"),
            ("새 비밀번호", "본인만 아는 3~128자 비밀번호를 두 번 입력"),
            ("비밀번호 저장", "저장하면 내 교육 화면으로 이동. 이후 비밀번호 변경은 프로필 메뉴에서 현재 비밀번호를 넣고 진행"),
        ],
    ))

    steps.append(_step(
        "STEP 2 · 내 교육", "참여할 교육 고르기",
        "로그인하면 나에게 배정된 교육과, 교육 전 검사부터 나의 리포트까지 네 단계 중 지금 어디인지가 보입니다.",
        _frame("내 교육", (
            _sidebar(("내 교육",), "내 교육", "참여자", pins=False, body=(
                '<div class="tg-row">' + _field("참여할 프로젝트", "2026 하반기 CS 역량 과정", pin=1) + '</div>'
                '<div class="tg-card"><div class="tg-title">2026 하반기 CS 역량 과정</div>'
                f'<div class="tg-sub">교육과정: {SAMPLE_PROJECT} · 교육일: 2026-11-12</div>'
                '<div class="tg-row"><span class="tg-tag muted">교육 전 미완료</span><span class="tg-tag muted">교육 후 미완료</span></div>'
                '<div class="tg-radio"><span class="on">1 교육 전 검사</span><span>2 교육 · 현업 적용</span><span>3 교육 후 검사</span><span>4 나의 리포트</span></div>'
                '<div class="tg-split">' + _btn("교육 전 검사", pin=2, full=True) + _btn("교육 후 검사", "secondary", pin=3, full=True) + '</div></div>'
            ))
        )),
        [
            ("참여할 프로젝트", "배정된 교육이 여러 개면 여기서 선택. 교육마다 응답은 따로 저장됨"),
            ("교육 전 검사", "교육 받기 전에 응답. 교육담당자가 정한 검사 기간에만 열림"),
            ("교육 후 검사", "교육 후 정해진 기간(보통 교육 8~10주 뒤)에 응답. 교육 전 검사를 먼저 마쳐야 열림"),
        ],
        note="배정된 교육이 없다는 안내가 보이면 교육담당자에게 배정을 요청하세요. 배정되면 이 화면에 나타납니다.",
    ))

    steps.append(_step(
        "STEP 3 · 검사 진행", "문항에 응답하기",
        "한 화면에 한 문항씩 나옵니다. <b>최근 8주 동안 실제 업무에서</b> 해당 행동을 얼마나 자주 했는지 골라 주세요.",
        _frame("교육 전 검사", (
            '<div class="tg-row">' + _btn("내 교육으로 돌아가기", "ghost", pin=1) + '</div>'
            '<div class="tg-row">' + _pin(2) + '<div class="tg-progress"><span style="width:21%"></span></div>'
            '<span class="tg-sub">5/24문항 저장됨</span></div>'
            '<div class="tg-card"><div class="tg-sub">고객지향 · 문항 6/24 · 최근 8주</div>'
            '<div class="tg-title">고객의 요구를 확인하기 위해 먼저 질문했다.</div>'
            '<div class="tg-row">' + _pin(3) + '<div class="tg-scale" style="flex:1"><span>1. 전혀 없었다</span><span>2. 드물게 있었다</span>'
            '<span class="hover">3. 가끔 있었다</span><span class="on">4. 자주 있었다</span><span>5. 거의 항상 있었다</span></div></div>'
            '<div class="tg-row">' + _pin(4) + '<span class="tg-zero">0. 수행 기회 없음</span></div>'
            '<div class="tg-row">' + _btn("← 이전 문항", "ghost", pin=5) + '<span class="tg-spacer"></span>' + _btn("다음 문항 →", "ghost") + '</div></div>'
        )),
        [
            ("내 교육으로 돌아가기", "중간에 나가도 저장된 문항까지는 남아 있어 다음에 이어서 응답 가능"),
            ("진행률", "지금까지 저장된 문항 수"),
            ("1~5 중 고르기", "오른쪽으로 갈수록 자주 한 것. "
             "<b>클릭하면 저장되고 다음 문항으로 넘어가므로 저장 버튼은 따로 없음</b>"),
            ("0. 수행 기회 없음", "최근 8주 동안 그런 상황 자체가 없었다면 막대 아래 이 버튼 선택. 0은 점수에 포함되지 않음"),
            ("이전 문항 · 다음 문항", "최종 제출 전까지 앞 문항으로 돌아가 응답 수정 가능. 이미 답한 문항은 다음 문항으로 넘어가면 됨. 마지막 문항에서는 <b>제출 준비 →</b>로 바뀜"),
        ],
        note="정답이 있는 시험이 아닙니다. 잘하고 싶은 모습이 아니라 <b>실제로 한 행동</b>을 기준으로 솔직하게 응답해 주세요.",
    ))

    steps.append(_step(
        "STEP 4 · 최종 제출", "응답 확인하고 제출하기",
        "모든 문항에 답하면 제출 화면이 나옵니다. 교육 후 검사에서는 현업 적용 환경 질문이 더 나옵니다.",
        _frame("최종 제출", (
            '<div class="tg-row"><div class="tg-progress"><span style="width:100%"></span></div><span class="tg-sub">24/24 역량문항 응답 완료</span></div>'
            '<div class="tg-exp"><div class="tg-exp-head">▾ 제출 전 내 응답 확인</div></div>'
            '<div class="tg-row">' + _btn("역량문항 응답 수정", "secondary", pin=1) + '</div>'
            + _btn("교육 전 검사 최종 제출", pin=2, full=True) +
            '<div class="tg-card"><div class="tg-sub">교육 후 검사에만 표시</div><div class="tg-title">현업전이 환경 확인</div>'
            '<div class="tg-sub">교육에서 배운 내용을 업무에 적용할 기회가 있었다.</div>'
            '<div class="tg-scale"><span>1. 전혀 그렇지 않다</span><span>2. 그렇지 않은 편이다</span><span>3. 보통이다</span>'
            '<span class="on">4. 그런 편이다</span><span>5. 매우 그렇다</span></div>'
            '<div class="tg-sub">적용을 방해한 요인(복수 선택)</div><div class="tg-checks">'
            '<span class="on">적용 기회 부족</span><span>상사·동료 지원 부족</span><span>도구·정보·권한 부족</span>'
            '<span class="on">시간·프로세스 제약</span><span>특별한 방해요인 없음</span></div>'
            + _field("실제 업무에 적용한 교육 내용(선택)", "", placeholder=True) +
            '<div class="tg-row">' + _btn("현업전이 응답 임시저장", "secondary", pin=3) + '</div>'
            + _btn("교육 후 검사 최종 제출", pin=4, full=True) + '</div>'
        )),
        [
            ("역량문항 응답 수정", "제출 전에 첫 문항부터 다시 보며 응답 수정 가능"),
            ("교육 전 검사 최종 제출", "누르면 교육 전 검사가 끝나고 교육 전 결과가 보임"),
            ("현업전이 응답 임시저장", "교육 후 검사에만 있음. 적용 기회, 상사 지원, 도구·정보·권한, 업무시간과 프로세스를 묻는 4문항(1~5)과 방해요인(복수 선택), 적용한 교육 내용(선택)을 중간 저장. 이 응답은 역량 점수에 합산되지 않음"),
            ("교육 후 검사 최종 제출", "현업전이 4문항에 모두 답해야 제출됨"),
        ],
        note="<b>최종 제출한 응답은 수정할 수 없습니다.</b>",
        warn=True,
    ))

    steps.append(_step(
        "STEP 5 · 결과 보기", "나의 교육 전후 리포트",
        "교육 전후 검사를 모두 마치면 내 교육 화면에 리포트 버튼이 생기고, PDF로도 내려받을 수 있습니다.",
        _frame("내 교육", (
            '<div class="tg-card"><div class="tg-title">2026 하반기 CS 역량 과정</div>'
            '<div class="tg-row"><span class="tg-tag">교육 전 완료</span><span class="tg-tag">교육 후 완료</span></div>'
            + _btn("나의 교육 전후 리포트 보기", pin=1, full=True) + '</div>'
            '<div class="tg-card"><div class="tg-row">' + _pin(2) + '<b>나의 교육 전후 리포트</b></div>' +
            _table(("역량", "교육 전(1~5)", "교육 후(1~5)", "관찰 변화"),
                   (("고객지향", "3.2", "3.9", "+0.7"), ("협업과 팀워크", "3.6", "3.8", "+0.2"), ("문제해결력", "2.9", "3.4", "+0.5"))) +
            '<div class="tg-bars"><div>고객지향<p><i style="width:64%"></i><i class="after" style="width:78%"></i></p></div></div>'
            + _btn("⤓ 내 리포트 PDF 다운로드", pin=3) + '</div>'
            '<div class="tg-card" style="background:#eef7f6"><div class="tg-sec">' + _pin(4) + '<i>★</i>보완 학습 제안</div>'
            '<div class="tg-sub">01 문제해결력 · 교육 후 3.00점, 목표 3.50점보다 0.50점 낮음</div>'
            '<div class="tg-mini"><span><i></i><b>[여의도] 논리적 문제해결</b><em>공개교육 · 최신 일정 보기</em></span>'
            '<span><i></i><b>문제해결 프레임워크</b><em>이러닝 · 수강 페이지 보기</em></span></div></div>'
        )),
        [
            ("나의 교육 전후 리포트 보기", "교육 전후 검사를 모두 최종 제출하면 나타남. 교육 전 검사만 마쳤다면 교육 전 결과만 볼 수 있음"),
            ("역량별 변화", "같은 문항에 두 번 모두 1~5로 답한 경우만 비교. 공통 유효문항이 부족한 역량은 점수 비공개. 아래에 내 현업전이 환경 응답이 이어짐"),
            ("내 리포트 PDF 다운로드", "교육 전후 결과, 레이더 차트, 업무 적용 가이드, 추천 과정을 담은 내 리포트를 PDF로 저장. 본인 결과이니 보관·공유에 주의"),
            ("보완 학습 제안", "교육 후 점수가 목표보다 0.2점 이상 낮은 역량마다 KMA 공개교육과 이러닝 카드. 버튼을 누르면 과정 페이지가 새 창에 열리며, 수강 여부는 교육담당자와 상의"),
        ],
        note="교육담당자는 교육 운영을 위해 개인별 교육 전후 리포트와, 역량별 응답자가 5명 이상일 때의 조직 결과를 볼 수 있습니다.",
    ))
    return steps


PARTICIPANT_FAQ = (
    ("비밀번호를 잊었어요", "교육담당자에게 임시 비밀번호 재발급을 요청해 주세요."),
    ("검사 기간이 아니라고 나와요", "검사 시작 전이거나 마감된 상태입니다. 기간은 교육담당자에게 문의해 주세요."),
    ("교육 후 검사 버튼이 안 열려요", "교육 전 검사를 먼저 최종 제출해야 합니다. 교육 후 검사 기간인지도 확인해 주세요."),
    ("중간에 창을 닫았어요", "다시 로그인하면 마지막으로 저장된 문항 다음부터 이어서 응답할 수 있습니다."),
)


def _faq(items: Iterable[tuple[str, str]]) -> str:
    cards = "".join(f"<div><strong>{q}</strong><p>{a}</p></div>" for q, a in items)
    return f'<div class="tg-faq">{cards}</div>'


# ---------------------------------------------------------------- page

def guide_sections() -> dict[str, list[str]]:
    """Return rendered HTML blocks per tab; used by the page and tests."""
    return {
        "manager": _manager_steps() + [_faq(MANAGER_FAQ)],
        "participant": _participant_steps() + [_faq(PARTICIPANT_FAQ)],
    }


# Replace this file to publish a new manual; the download name stays the same.
GUIDE_PDF_PATH = Path(__file__).resolve().parents[1] / "docs" / "TAP_사용설명서.pdf"


@lru_cache(maxsize=1)
def _guide_pdf() -> bytes | None:
    return GUIDE_PDF_PATH.read_bytes() if GUIDE_PDF_PATH.is_file() else None


def render_account_guide():
    from tap.account_portal import TOKEN_KEY

    st.html(brand_css() + account_theme_css() + GUIDE_CSS)
    signed_in = bool(st.session_state.get(TOKEN_KEY))
    with st.container(key="tap_guide_shell"):
        with st.container(key="tap_guide_header"):
            st.markdown(brand_html(), unsafe_allow_html=True)
            st.title("이용 안내")
            st.caption("탭에서 역할을 고르세요. 화면 예시의 번호와 설명 번호가 같습니다.")
            if signed_in:
                if st.button("업무 화면으로 돌아가기", icon=":material/arrow_back:", key="tap_guide_back"):
                    switch_to_page("home")
            else:
                st.markdown("[로그인하기](/login)")
            guide_pdf = _guide_pdf()
            if guide_pdf:
                st.download_button("PDF 사용설명서 내려받기", guide_pdf, "TAP_사용설명서.pdf", "application/pdf",
                                   icon=":material/download:", key="tap_guide_pdf")

        st.html(_intro())
        sections = guide_sections()
        manager_tab, participant_tab = st.tabs(["교육담당자", "참여자"], key="tap_guide_tabs")
        with manager_tab:
            st.html('<div class="tg-flow"><span>참여자 계정 발급</span><em>→</em><span>프로젝트 만들기</span><em>→</em>'
                    '<span>참여자 배정</span><em>→</em><span>현황 확인</span><em>→</em><span>리포트</span></div>')
            for block in sections["manager"]:
                st.html(block)
        with participant_tab:
            st.html('<div class="tg-flow"><span>로그인</span><em>→</em><span>내 교육 확인</span><em>→</em>'
                    '<span>교육 전 검사</span><em>→</em><span>교육 후 검사</span><em>→</em><span>나의 리포트</span></div>')
            for block in sections["participant"]:
                st.html(block)
