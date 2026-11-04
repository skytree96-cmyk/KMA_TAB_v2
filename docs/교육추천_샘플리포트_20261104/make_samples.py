"""Build five sample reports with designed weak competencies through the real report code path.

Run from gcp-cloudrun: python make_samples.py <out_dir>
Responses are fixed per item (no random answers): weak competencies get low item scores on purpose.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, ".")

from tap.account_admin_ui import build_project_config  # noqa: E402
from tap.account_insights import recommend_courses, summarize_transfer  # noqa: E402
from tap.account_reports import _organization_courses, export_report_pdf, individual_report_pdf, summarize_project  # noqa: E402
from tap.data import load_competencies, questions_for_factors  # noqa: E402
from tap.scoring import score_pre_post_responses  # noqa: E402

OUT = Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
NAMES = {row["factor_code"]: row["factor_name_ko"] for row in load_competencies()}
SOURCE_LABELS = {"public_edu_center": "공개교육", "studio_elearning": "이러닝", "b2b_inquiry": "단체교육 문의",
                 "studio_original": "stud.io 오리지널"}

# Item answers (4 items per competency). Anything not listed is answered STRONG.
STRONG = ([4, 4, 4, 3], [4, 4, 5, 4])  # pre 3.75 -> post 4.25

CASES = [
    {
        "slug": "01_실무자_데이터분석·AI활용_부족",
        "level": "staff", "optional": ["AI_USE", "DATA_ANA"], "priorities": ["DATA_ANA"], "delivery": "all",
        "project": "2026 하반기 실무자 데이터 리터러시", "course": "업무 데이터 분석 실무",
        "design": "데이터 분석·해석과 AI 도구 활용을 낮게 응답. 교육 후 데이터 분석은 조금 오르고 AI 활용은 그대로.",
        "answers": {"DATA_ANA": ([2, 2, 3, 2], [3, 2, 3, 2]),   # 2.25 -> 2.50
                    "AI_USE": ([3, 2, 3, 3], [3, 3, 2, 3])},    # 2.75 -> 2.75
    },
    {
        "slug": "02_신임팀장_사람육성·소통_부족",
        "level": "manager", "optional": [], "priorities": ["LEAD-PD", "LEAD-CI"], "delivery": "offline",
        "project": "2026 신임 팀장 리더십", "course": "신임 팀장 리더십 과정",
        "design": "사람 육성, 소통과 영향력, 전략적 사고를 낮게 응답. 교육 후 사람 육성만 0.5점 오름. 집합교육 선호.",
        "answers": {"LEAD-PD": ([2, 2, 2, 2], [3, 2, 3, 2]),    # 2.00 -> 2.50
                    "LEAD-CI": ([3, 3, 2, 3], [3, 3, 3, 3]),    # 2.75 -> 3.00
                    "JOB-ST": ([3, 4, 3, 3], [3, 4, 3, 3])},    # 3.25 -> 3.25
    },
    {
        "slug": "03_영업실무자_영업·설득·고객지향_부족",
        "level": "staff", "optional": ["COMM_PRES", "SALES_CORE"], "priorities": ["SALES_CORE"], "delivery": "online",
        "project": "2026 B2B 영업 역량 강화", "course": "B2B 영업 실무 과정",
        "design": "영업 핵심역량, 설득·프레젠테이션, 고객지향을 낮게 응답. 이러닝 선호. 영업 역량은 이러닝 연결이 없는 역량.",
        "answers": {"SALES_CORE": ([2, 3, 2, 2], [3, 3, 2, 2]),  # 2.25 -> 2.50
                    "COMM_PRES": ([3, 2, 3, 3], [3, 3, 3, 2]),   # 2.75 -> 2.75
                    "CORE-CO": ([3, 3, 3, 3], [3, 3, 3, 3])},    # 3.00 -> 3.00
    },
    {
        "slug": "04_PM관리자_프로젝트관리·변화추진_하락",
        "level": "manager", "optional": ["CHANGE_MG", "PM_EXEC"], "priorities": [], "delivery": "all", "target": 4.0,
        "project": "2026 프로젝트 리더 육성", "course": "프로젝트 리더 과정",
        "design": "목표 4.0. 프로젝트 실행·관리는 교육 후 오히려 0.5점 하락, 변화 수용·추진과 실행력은 변화 없음.",
        "answers": {"PM_EXEC": ([3, 4, 3, 3], [3, 3, 2, 3]),    # 3.25 -> 2.75
                    "CHANGE_MG": ([3, 3, 3, 3], [3, 3, 3, 3]),  # 3.00 -> 3.00
                    "JOB-EX": ([3, 4, 3, 3], [3, 3, 4, 3])},    # 3.25 -> 3.25
    },
]

# Organization case: six participants; DX, ESG and strategic thinking stay low across the group.
ORG_CASE = {
    "slug": "05_조직리포트_DX·ESG·전략적사고_부족",
    "level": "manager", "optional": ["DX_APPLY", "ESG_PRAC"], "priorities": ["DX_APPLY"], "delivery": "all",
    "project": "2026 중간관리자 DX 전환", "course": "DX 리더 과정",
    "design": "관리자 6명. 디지털 혁신 적용, ESG 이해·실천, 전략적 사고가 조직 평균에서 낮게 나오도록 응답. "
              "현업전이 응답에서 도구·정보·권한을 낮게 줌.",
    "people": [
        {"DX_APPLY": ([2, 2, 3, 2], [3, 2, 3, 3]), "ESG_PRAC": ([3, 2, 3, 3], [3, 3, 3, 3]), "JOB-ST": ([3, 3, 3, 3], [3, 3, 3, 4])},
        {"DX_APPLY": ([2, 3, 2, 2], [2, 3, 3, 2]), "ESG_PRAC": ([2, 3, 3, 2], [3, 3, 3, 2]), "JOB-ST": ([3, 3, 4, 3], [3, 3, 3, 3])},
        {"DX_APPLY": ([3, 2, 2, 3], [3, 3, 2, 3]), "ESG_PRAC": ([3, 3, 3, 3], [3, 3, 2, 3]), "JOB-ST": ([3, 3, 3, 3], [3, 3, 3, 3])},
        {"DX_APPLY": ([2, 2, 2, 3], [3, 3, 3, 2]), "ESG_PRAC": ([3, 2, 2, 3], [3, 3, 3, 3]), "JOB-ST": ([4, 3, 3, 3], [3, 4, 3, 3])},
        {"DX_APPLY": ([3, 3, 2, 2], [3, 2, 3, 3]), "ESG_PRAC": ([3, 3, 3, 2], [3, 2, 3, 3]), "JOB-ST": ([3, 3, 3, 3], [3, 3, 3, 3])},
        {"DX_APPLY": ([2, 2, 3, 3], [3, 3, 3, 3]), "ESG_PRAC": ([2, 3, 3, 3], [3, 3, 3, 3]), "JOB-ST": ([3, 3, 3, 4], [3, 3, 4, 3])},
    ],
    "transfer": {"application_opportunity": 3, "supervisor_support": 4, "resources_authority": 2,
                 "time_process_support": 3, "barriers": ["도구·정보·권한 부족"]},
}


def make_config(case: dict) -> dict:
    config = build_project_config(case["project"], case["course"], case["level"], case["optional"],
                                  date(2026, 11, 20), date(2026, 11, 9), date(2026, 11, 19), date(2026, 12, 21),
                                  date(2027, 1, 8), case.get("target", 3.5), case["priorities"], case["delivery"])
    config["question_snapshot"] = questions_for_factors(config["selected_factors"])
    return config


def responses(questions: list[dict], answers: dict) -> tuple[dict, dict]:
    pre, post = {}, {}
    by_factor: dict[str, list[dict]] = {}
    for question in questions:
        by_factor.setdefault(question["factor_code"], []).append(question)
    for code, items in by_factor.items():
        items.sort(key=lambda q: int(q.get("item_order") or 0))
        pre_items, post_items = answers.get(code, STRONG)
        for item, a, b in zip(items, pre_items, post_items, strict=True):
            pre[item["question_code"]] = a
            post[item["question_code"]] = b
    return pre, post


def course_rows(courses: list[dict]) -> list[dict]:
    return [{"역량": c["factor_name_ko"], "과정명": c["title"], "구분": SOURCE_LABELS.get(c.get("source"), c.get("source")),
             "방식": c.get("delivery_label"), "일정": c.get("schedule"), "대상": c.get("target_level"),
             "근거": c.get("reason"), "안내": c.get("advice"), "링크": c.get("url"), "course_id": c.get("course_id")}
            for c in courses]


summary = []
for case in CASES:
    config = make_config(case)
    questions = config["question_snapshot"]
    pre, post = responses(questions, case["answers"])
    project = {"name": case["project"], "company_name": "샘플 회원사", "config": config}
    subject = f"샘플 참여자 {case['slug'][:2]}"
    pdf = individual_report_pdf(project, questions, pre, post, subject)
    (OUT / f"{case['slug']}.pdf").write_bytes(pdf)
    scores = score_pre_post_responses(questions, pre, post, config["target_means"])
    in_pdf = recommend_courses(config, scores, limit=6)  # the PDF and the participant screen show the same six
    summary.append({
        "slug": case["slug"], "kind": "individual", "level": case["level"], "delivery": case["delivery"],
        "target": case.get("target", 3.5), "priorities": [NAMES[c] for c in case["priorities"]],
        "design": case["design"],
        "scores": [{"역량": r["factor_name_ko"], "교육 전": r["pre_score"], "교육 후": r["post_score"]} for r in scores],
        "pdf_courses": course_rows(in_pdf),
    })

# Organization report through export_report_pdf with an in-memory store.
case = ORG_CASE
config = make_config(case)
questions = config["question_snapshot"]
results = []
for index, answers in enumerate(case["people"], start=1):
    pre, post = responses(questions, answers)
    results.append({"id": str(index), "user_id": f"u{index}", "user_name": f"참여자{index}", "login_id": f"sample{index}",
                    "pre_completed": True, "post_completed": True, "pre_payload": {"responses": pre},
                    "post_payload": {"responses": post, "post_transfer_responses": dict(case["transfer"])}})


class MemoryStore:
    def project_results(self, token, project_id):
        return results


project = {"id": "sample-org", "name": case["project"], "company_name": "샘플 회원사", "config": config}
(OUT / f"{case['slug']}.pdf").write_bytes(export_report_pdf(MemoryStore(), "token", project))
summaries = summarize_project(project, results)
org_courses = _organization_courses(config, summaries)
summary.append({
    "slug": case["slug"], "kind": "organization", "level": case["level"], "delivery": case["delivery"], "target": 3.5,
    "priorities": [NAMES[c] for c in case["priorities"]], "design": case["design"], "people": len(case["people"]),
    "scores": [{"역량": r["factor_name_ko"], "교육 전": r["pre_mean"], "교육 후": r["post_mean"]} for r in summaries],
    "transfer": summarize_transfer(results), "pdf_courses": course_rows(org_courses),
})

(OUT / "추천결과_원자료.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
for row in summary:
    print("=" * 100)
    print(row["slug"], row["kind"], row["level"], row["delivery"], "target", row["target"], "priorities", row["priorities"])
    for s in row["scores"]:
        print("   ", s)
    print("  -- PDF")
    for c in row["pdf_courses"]:
        print(f"    [{c['역량']}] {c['구분']} | {c['과정명']} | {c['일정']} | 대상 {c['대상']} | {c['근거']}")
