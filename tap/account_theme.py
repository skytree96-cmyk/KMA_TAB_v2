"""Shared presentation for production account screens; no routing or data access."""
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "assets"
# Paperlogy (OFL) dynamic subset, the same source PAI uses; browsers fetch only the glyph ranges in use.
FONT_IMPORT = ('<style>@import url("https://cdn.jsdelivr.net/gh/fonts-archive/Paperlogy/subsets/'
               'Paperlogy-dynamic-subset.css");</style>')

# Action panels (st.expander) by widget-key prefix: tone, Material Symbols icon, one-line description.
# Tones map to design tokens: brand=people, indigo=operations, violet=results, amber=caution, red=danger.
PANEL_TONES = {
    "account_admin_workspace_issue_": ("brand", "person_add", "아이디와 이름을 입력해 계정을 한 명씩 만들고 임시 비밀번호를 발급합니다."),
    "account_admin_batch_expander_": ("indigo", "upload_file", "CSV 양식으로 여러 명의 계정을 한 번에 등록합니다."),
    "account_admin_assignment_panel_": ("amber", "swap_horiz", "잘못 배정한 참여자의 배정을 해제하거나 다시 배정합니다."),
    "_tap_participant_review_panel": ("brand", "fact_check", "최종 제출 전에 내가 고른 응답을 한눈에 확인합니다."),
    "_tap_participant_transfer_panel": ("violet", "insights", "교육 후 검사에서 답한 현업 적용 환경을 다시 봅니다."),
}


def _read(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def _panel_css() -> str:
    rules = []
    for prefix, (tone, icon, description) in PANEL_TONES.items():
        quoted = description.replace("\\", "\\\\").replace('"', '\\"')
        rules.append(
            f'.stApp [class*="st-key-{prefix}"] > [data-testid="stExpander"]'
            f'{{--tone:var(--{tone});--tone-pale:var(--{tone}-pale);--panel-desc:"{quoted}";--panel-icon:"{icon}";}}'
        )
    return "\n".join(rules)


@lru_cache(maxsize=1)
def account_theme_css() -> str:
    # The premium layer follows account-ui.css so its tokens and components win.
    return FONT_IMPORT + "<style>" + _read("account-ui.css") + _read("premium-base.css") + _panel_css() + "</style>"


@lru_cache(maxsize=1)
def workspace_theme_css() -> str:
    return "<style>" + _read("workspace-ui.css") + _read("premium-workspace.css") + "</style>"
