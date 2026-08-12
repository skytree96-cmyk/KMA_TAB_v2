from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"

APP_TITLE = "TAP | 교육 역량진단"
APP_SUBTITLE = "현재 행동을 확인하고, 필요한 학습을 연결합니다."

MIN_VALID_ITEMS = 3
MIN_GROUP_N = 5
NA_VALUE = 0

LIKERT_OPTIONS = {
    0: "수행 기회 없음",
    1: "전혀 없었다",
    2: "드물게 있었다",
    3: "가끔 있었다",
    4: "자주 있었다",
    5: "거의 항상 있었다",
}

FREQUENCY_LEVELS = (
    (4.20, "임시 기술구간 · 매우 높은 빈도"),
    (3.40, "임시 기술구간 · 높은 빈도"),
    (2.60, "임시 기술구간 · 중간 빈도"),
    (1.80, "임시 기술구간 · 낮은 빈도"),
    (1.00, "임시 기술구간 · 매우 낮은 빈도"),
)

SOURCE_URLS = {
    "testing_standards": "https://www.testingstandards.net/uploads/7/6/6/4/76643089/standards_2014edition.pdf",
    "cdc_cognitive_interview": "https://www.cdc.gov/nchs/ccqder/question-evaluation/cognitive-interviewing.html",
    "cdc_needs_analysis": "https://www.cdc.gov/training-development/php/about/assess-training-needs-conducting-needs-analysis.html",
    "streamlit_deploy": "https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app",
}
