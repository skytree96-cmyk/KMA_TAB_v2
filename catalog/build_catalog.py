"""Mapping rules: public courses, inquiry (B2B) courses and e-learning -> TAP competencies.

Runs in the work directory (see catalog/run_weekly.py). Reads kma_offline_live.csv and lxp_to_studio_match.csv
written by the crawl steps, plus catalog/inputs/kma_b2b_courses.csv and studio_original.csv. Writes
kma_course_catalog_v3.csv, kma_competency_course_map_v3.csv and catalog_v3_summary.txt.
"""
import io, collections, csv, re, html, hashlib

from catalog.common import INPUTS, read_csv

MIN_FIT = 0.6   # 이 미만은 매핑 저장 안 함
# 카테고리로 잡힌 역량을 제목도 뒷받침하면 더하는 값. 같은 카테고리 안에서 제목이 맞는 과정이 먼저 나온다.
TITLE_CONFIRM_BONUS = 0.05
# 특정 업종 전용 과정은 일반 역량 추천에 넣지 않는다(의료기관 ESG 등). 제목에 업종이 드러나면 전부 저장 기준 아래로 내린다.
INDUSTRY_ONLY = r"의료기관|병원|의료진|간호|메디컬"

# ---------- 1) 공개교육센터 카테고리 -> 역량 ----------
CAT_MAP = {
    "교육>AX 혁신>생성형 AI 입문": [("AI_USE", 0.95), ("DX_APPLY", 0.7)],
    "교육>AX 혁신>생성형AI 실무 활용": [("AI_USE", 0.9)],
    "교육>AX 혁신>생성형AI 직무 특화": [("AI_USE", 0.8)],
    "교육>AX 혁신>데이터 분석": [("DATA_ANA", 0.95), ("DATA_JOB", 0.7)],
    "교육>AX 혁신>AI 리더십": [("DX_APPLY", 0.75), ("CHANGE_MG", 0.65)],
    "교육>리더십∙코칭>리더십": [("LEAD-PD", 0.85), ("LEAD-CI", 0.75)],
    "교육>리더십∙코칭>코칭": [("LEAD-PD", 0.95)],
    "교육>리더십∙코칭>셀프리더십": [("CORE-GM", 0.85)],
    "교육>리더십∙코칭>마음챙김": [("CORE-GM", 0.6)],
    "교육>리더십∙코칭>조직문화": [("CHANGE_MG", 0.8), ("CORE-CL", 0.65)],
    "교육>리더십∙코칭>인문학리더십": [("LEAD-CI", 0.6)],
    "교육>직급·승진자>신임·승진자": [("LEAD-PD", 0.7), ("LEAD-CI", 0.7)],
    "교육>직급·승진자>직급별 역량": [("JOB-EX", 0.6), ("LEAD-CI", 0.6)],
    "교육>직급·승진자>임원": [("JOB-ST", 0.8)],
    "교육>비즈니스 스킬>커뮤니케이션": [("LEAD-CI", 0.85), ("COMM_PRES", 0.75), ("CORE-CL", 0.6)],
    "교육>비즈니스 스킬>문서작성": [("COMM_PRES", 0.85), ("PLAN_STR", 0.65)],
    "교육>비즈니스 스킬>문제해결": [("JOB-PS", 0.95)],
    "교육>비즈니스 스킬>업무생산성": [("JOB-EX", 0.75), ("DX_APPLY", 0.65)],
    "교육>비즈니스 스킬>OA": [("DATA_ANA", 0.6)],
    "교육>비즈니스 스킬>외국어": [("GLOBAL_BZ", 0.9)],
    "교육>인적자원(HR)>인사∙노무∙법무": [("HR_CORE", 0.8), ("LEGAL_CORE", 0.6)],
    "교육>인적자원(HR)>HRD": [("HR_CORE", 0.85)],
    "교육>인적자원(HR)>성과관리": [("HR_CORE", 0.8), ("LEAD-PD", 0.7)],
    "교육>인적자원(HR)>강사역량": [("COMM_PRES", 0.7)],
    "교육>전략·기획>전략∙기획": [("JOB-ST", 0.9), ("PLAN_STR", 0.9), ("STRAT_CORE", 0.8)],
    "교육>전략·기획>사업계획": [("PLAN_STR", 0.8)],
    "교육>전략·기획>프로젝트관리": [("PM_EXEC", 0.95)],
    "교육>전략·기획>고객경험(CX)": [("CORE-CO", 0.9)],
    "교육>전략·기획>ESG": [("ESG_PRAC", 0.95)],
    "교육>전략·기획>R&D": [("RND_CORE", 0.95)],
    "교육>직무>CS·컨택센터": [("CORE-CO", 0.85)],
    "교육>직무>영업": [("SALES_CORE", 0.95)],
    "교육>직무>마케팅·SNS": [("MKT_CORE", 0.95)],
    "교육>직무>재무·회계": [("FIN_CORE", 0.95)],
    "교육>직무>구매∙원가": [("PROC_CORE", 0.95)],
    "교육>직무>생산∙품질": [("MFG_CORE", 0.95)],
    "교육>직무>무역·물류": [("LOGI_CORE", 0.8)],
}
EXCLUDE_CAT_PREFIX = ("교육>해외연수", "교육>평생교육", "교육>세미나·포럼", "교육>SPECIAL", "교육>직급·승진자>최고경영자")

# ---------- 2) 제목 키워드 보정 (정밀 패턴) ----------
TITLE_BOOST = [
    (r"보고서|기획서|문서작성|문서 작성|구두보고|보고 스킬|제안서", [("COMM_PRES", 0.8)]),
    (r"프레젠테이션|스피치|발표|보이스", [("COMM_PRES", 0.9), ("LEAD-CI", 0.7)]),
    (r"설득|협상", [("LEAD-CI", 0.85)]),
    (r"기획력|사업기획|신사업|전략 ?기획|기획안|기획 및|서비스 기획|교육기획|기회 발굴", [("PLAN_STR", 0.85)]),
    (r"전략적 사고|경영전략|사업전략|KPI|전략 수립|전략기획", [("JOB-ST", 0.85), ("STRAT_CORE", 0.85)]),
    # 분석 자체를 다루는 제목이 도구(엑셀·BI) 제목보다 먼저 나오도록 두 단계로 나눈다.
    (r"데이터 ?분석|데이터 기반|데이터 전처리|데이터 리터러시|통계|시각화|애널리틱스|Pandas|판다스", [("DATA_ANA", 0.85)]),
    (r"엑셀|파워 ?BI|Power ?BI|GA4", [("DATA_ANA", 0.75)]),
    (r"python|파이썬|SQL|빅데이터|머신러닝|딥러닝|크롤링|대시보드", [("DATA_JOB", 0.9)]),
    (r"HRD|\bHR\b|인사(?!이트)|노무|채용|면접|급여|교육담당|교육운영|인재(경영|육성|관리)|직무분석|고충처리|괴롭힘|성희롱", [("HR_CORE", 0.85)]),
    (r"법무|법률|계약서|소송|회생|파산|컴플라이언스|법적|등기|노동법|근로기준법|통상임금", [("LEGAL_CORE", 0.9)]),
    (r"마케팅|브랜드|콘텐츠 ?마케팅|인스타그램|숏폼|라이브커머스|SNS|유튜브|광고", [("MKT_CORE", 0.85)]),
    (r"영업|세일즈|B2B", [("SALES_CORE", 0.85)]),
    (r"재무|회계|손익|원가|세무|결산|법인세|연말정산|예산|가치평가|채권", [("FIN_CORE", 0.85)]),
    (r"프로젝트 ?관리|프로젝트 매니지먼트|\bPM\b|PMO|리스크 매니지먼트|일정 관리", [("PM_EXEC", 0.9)]),
    (r"코칭(?!실습)|피드백|면담|동기부여|육성|온보딩|멘토", [("LEAD-PD", 0.85)]),
    (r"신임 ?팀장|팀장|관리자 역량|리더십 스킬|리더의", [("LEAD-PD", 0.7), ("LEAD-CI", 0.65)]),
    (r"문제 ?해결|의사결정|로지컬|논리적 사고|창의적 사고", [("JOB-PS", 0.85)]),
    (r"협업과|팀워크|팔로워십|갈등 ?(관리|해결|상황)|대인관계|관계 커뮤니케이션|세대 ?간|심리적 안전감", [("CORE-CL", 0.8)]),
    (r"고객 ?(경험|응대|만족|불만|여정|중심)|\bCS\b|CX|서비스 접점|MOT|민원|컨택센터|블랙컨슈머", [("CORE-CO", 0.85)]),
    (r"변화 ?(관리|리더십|수용|추진|대응)|체인지|조직문화|조직개발|조직진단|Culture", [("CHANGE_MG", 0.85)]),
    (r"업무 ?자동화|자동화|노션|Notion|스마트워크|워크스페이스|Copilot|코파일럿|디지털 전환|DX|AX", [("DX_APPLY", 0.8)]),
    (r"실행력|목표관리|성과관리|시간관리|업무관리|OKR|워크다이어트|일하는 방식|업무 프로세스", [("JOB-EX", 0.9)]),
    (r"글로벌 비즈니스|글로벌 협상|해외 ?진출|해외 ?마케팅|비즈니스 ?영어|영어|영문|이문화|무역", [("GLOBAL_BZ", 0.8)]),
    (r"ESG|탄소|온실가스|기후|지속가능|인권경영|생물다양성", [("ESG_PRAC", 0.9)]),
    (r"물류|SCM|공급사슬|공급망|재고|로지스틱스|수출입통관", [("LOGI_CORE", 0.95)]),
    (r"구매|조달|협력업체|협력사", [("PROC_CORE", 0.9)]),
    (r"생산(?!성)|품질|공정(?!성)|제조|현장 ?5S|린\(Lean\)|QMS", [("MFG_CORE", 0.9)]),
    (r"특허|R&D|연구개발|기술전략|기술기획", [("RND_CORE", 0.9)]),
    (r"홍보|\bPR\b|언론|보도자료|미디어 대응|위기 ?커뮤니케이션|평판|기업 커뮤니케이션", [("PR_CORE", 0.85)]),
    (r"ChatGPT|생성형 ?AI|Gemini|Claude|Copilot|프롬프트|GPT|AI 활용|AI로|AI를 활용", [("AI_USE", 0.85)]),
    (r"아이디어|창의|디자인 ?씽킹|혁신 워크숍|실험", [("INNOV_ID", 0.8)]),
    (r"셀프리더십|자기관리|자기이해|강점|커리어|회복탄력성|성장 루틴|잡 크래프팅", [("CORE-GM", 0.8)]),
    (r"프로그래밍|코딩|개발 제대로|앱 개발|웹 개발|Kotlin|Java|자바", [("DEV_CORE", 0.85)]),
]
# 특정 역량에 대해 제목에 이 패턴이 있으면 적합도 상한을 낮춘다 (오탐 억제)
CAP_RULES = [
    ("CHANGE_MG", r"기후변화|정책 변화|노동정책|판결", 0.0),
    ("CORE-CL", r"AI와 협업|AI 협업|ESG|고충처리|성희롱|괴롭힘|민원", 0.0),
    ("CORE-CL", r"프레젠테이션|스피치|보이스", 0.0),
    ("LEAD-PD", r"셀프리더십|자기관리|자기이해|스피치", 0.5),
    ("LEAD-PD", r"KPC|KAC|코칭실습|자격", 0.7),
    ("LEAD-CI", r"프레젠테이션|스피치|보이스|PPT", 0.7),
    ("COMM_PRES", r"Claude Code|업무 자동화|자동화", 0.5),
    ("GLOBAL_BZ", r"ISO|QMS|생물다양성|자연자본", 0.0),
    ("PLAN_STR", r"예산|손익|원가|가치평가|재무|품질기획|SPC", 0.5),
    ("JOB-ST", r"공모사업|제안서|경영평가", 0.7),
    ("HR_CORE", r"회생|파산|변호사|계약서|법적 사고|법률전문직", 0.4),
    ("DX_APPLY", r"문제 해결|문제해결|비즈니스 모델", 0.5),
    ("PM_EXEC", r"AI 프로젝트|앱\(APP\) 개발|서비스 구현|업무자동화 프로젝트", 0.4),
    ("DATA_ANA", r"데이터베이스 연동|Streamlit|앱을 파이썬", 0.4),
    ("DATA_ANA", r"머신러닝|딥러닝|인공지능 개발|알고리즘", 0.75),   # 모델 개발은 데이터 분석 전문역량(DATA_JOB) 쪽
    ("CORE-CO", r"CSS|Docs|HTML", 0.0),
    ("JOB-EX", r"파이썬|ChatGPT|생성형|Claude|GPT|자동화 프로그램", 0.65),
    ("ESG_PRAC", r"내부감사|내부통제|금융윤리", 0.6),
    ("LOGI_CORE", r"무역|신용장|수입전문가|FTA", 0.75),
    # --- 2차 검수 반영 ---
    ("AI_USE", r"Photoshop|포토샵|영상 제작|더빙", 0.6),
    ("COMM_PRES", r"더빙|영상 제작|AI 보이스", 0.0),
    ("COMM_PRES", r"Google Workspace|Slides|슬라이드", 0.65),
    ("CORE-CL", r"DISC|전문가 양성", 0.0),
    ("CORE-GM", r"실행력|질문력|리더의|산업재해", 0.5),
    ("DATA_ANA", r"SPC|품질", 0.5),
    ("DATA_JOB", r"기획력|GUI|Programming|PyCharm|업무자동화|앱을 파이썬|Streamlit", 0.6),
    ("DX_APPLY", r"C#|스프링|Spring|자바|Java|GitHub", 0.0),
    ("GLOBAL_BZ", r"금융|공모주식|구매협상|업무의 방향", 0.5),
    ("INNOV_ID", r"인생|행복|삶|교수법", 0.0),
    ("JOB-PS", r"행동경제학", 0.6),
    ("JOB-ST", r"기획안|기획서|제안서|보고서|ESG|의료|마케팅", 0.65),
    ("STRAT_CORE", r"기획안|기획서|제안서|보고서|ESG|의료|마케팅|특허|IP 전략", 0.6),
    ("LEAD-CI", r"보고서|기획서|기획안", 0.65),
    ("LEAD-CI", r"영업|세일즈|구매", 0.7),
    ("LEAD-PD", r"사원급|신규 입사자|셀프코칭|온보딩 과정", 0.5),
    ("LEGAL_CORE", r"국토|부동산|면접|직무분석|급여|HRD|교육|금융", 0.5),
    ("MFG_CORE", r"현직자|직무 -|제조업 분야", 0.6),
    ("PROC_CORE", r"ESG|키트|아두이노|자금조달|부동산|마케팅", 0.5),
    ("RND_CORE", r"웹 데이터|수집|현직자", 0.6),
]

def apply(name, fits, cap=1.0):
    from_category = {code for code, fit in fits.items() if fit >= MIN_FIT}   # 저장 기준에 못 미치는 약한 카테고리는 보너스 없음
    confirmed = set()
    for pat, boosts in TITLE_BOOST:
        if re.search(pat, name, re.I):
            for code, fit in boosts:
                fits[code] = max(fits.get(code, 0), min(fit, cap))
                if code in from_category:
                    confirmed.add(code)
    for code in confirmed:
        fits[code] = min(1.0, fits[code] + TITLE_CONFIRM_BONUS)

def finalize(name, fits):
    if re.search(INDUSTRY_ONLY, name, re.I):
        fits = {code: min(fit, MIN_FIT - 0.1) for code, fit in fits.items()}
    for code, pat, cap in CAP_RULES:
        if code in fits and re.search(pat, name, re.I):
            fits[code] = min(fits[code], cap)
    return {k: round(v, 2) for k, v in fits.items() if v >= MIN_FIT}

def level_of(name):
    if re.search(r"임원|경영자|CEO", name): return "executive"
    if re.search(r"팀장|관리자|리더|매니저", name): return "manager"
    if re.search(r"신입|사원|2-3년차|주니어", name): return "staff"
    return "all"

catalog, mapping = [], []
def add(course, fits, basis):
    if not fits:
        return False
    catalog.append(course)
    for code, fit in fits.items():
        mapping.append({"factor_code": code, "course_id": course["course_id"], "content_fit": fit, "basis": basis})
    return True

BASE = {"next_start": "", "next_end": "", "next_crsseq_id": "", "schedule_count": "", "edu_day": "", "edu_time": "",
        "place": "", "fee_member": "", "fee_nonmember": "", "thumb_url": "", "crscd": "", "dev_ym": ""}

# 1) 공개교육센터 라이브
excluded = collections.Counter()
for r in csv.DictReader(io.open("kma_offline_live.csv", encoding="utf-8-sig")):
    cat, name = r["category"], html.unescape(r["crs_nm"])
    if cat.startswith(EXCLUDE_CAT_PREFIX):
        excluded[cat.split(">")[1]] += 1; continue
    if r.get("detail_ok") == "False":   # crawl_kma_thumbs.py가 상세 페이지 오류를 확인한 과정
        excluded["상세페이지 오류"] += 1; continue
    fits = {code: fit for code, fit in CAT_MAP.get(cat, [])}
    apply(name, fits)
    fits = finalize(name, fits)
    if not fits:
        excluded["매핑없음:" + cat] += 1; continue
    add({**BASE, "course_id": f"KMA-OFF-{r['crscd']}", "source": "public_edu_center", "title": name,
         "delivery": "online_live" if name.startswith("[비대면]") else "offline", "target_level": level_of(name),
         "category": cat, "crscd": r["crscd"], "next_start": r["next_start"], "next_end": r["next_end"],
         "next_crsseq_id": r["next_crsseq_id"], "schedule_count": r["schedule_count"],
         "has_upcoming": r["has_upcoming"] == "True", "edu_day": r["edu_day"], "edu_time": r["edu_time"],
         "place": r["place"], "fee_member": r["fee_member"], "fee_nonmember": r["fee_nonmember"],
         "url": r["url_evergreen"], "thumb_url": r["thumb_url"]}, fits, "category+title")

# 2) 교육문의형(B2B) — 조직 리포트 전용. 제목만 사용, 태그는 보조(상한 0.6)
B2B_MAP = {
    "기업교육>역량별 솔루션>조직역량": [("CORE-CL", 0.65), ("CHANGE_MG", 0.6)],
    "기업교육>AI 교육>역량 특화교육": [("AI_USE", 0.7)],
    "기업교육>AI 교육>직무 특화교육": [("AI_USE", 0.6)],
    "기업교육>AI 교육>일반교육": [("AI_USE", 0.7), ("DX_APPLY", 0.6)],
    "기업교육>AI 교육>기술 특화교육": [("AI_USE", 0.6)],
}
for r in read_csv(INPUTS / "kma_b2b_courses.csv"):
    cat, name = str(r["TREE_CTGRY_NM"]), str(r["CRS_NM"])
    fits = {code: fit for code, fit in B2B_MAP.get(cat, [])}
    apply(name, fits, cap=0.85)
    tag_fits = {}
    apply(str(r.get("TAG") or ""), tag_fits, cap=0.6)
    for code, fit in tag_fits.items():
        fits[code] = max(fits.get(code, 0), fit)
    fits = finalize(name, fits)
    add({**BASE, "course_id": f"KMA-B2B-{r['CRSCD']}", "source": "b2b_inquiry", "title": name, "delivery": "inhouse",
         "target_level": "all", "category": cat, "crscd": str(r["CRSCD"]), "has_upcoming": True,
         "url": ("https://www.kma.or.kr/usrs/eduRegMgnt/eduRegInfoDetailForm.do?p_edutype_cd=003"
                 f"&p_crscd={r['CRSCD']}&p_crsseq_id=&p_view_type=S&p_ctgry_id={r['CRS_CTGRY_ID']}&CRSCD={r['CRSCD']}"
                 f"&CRSSEQ_ID=&p_hmpgcd=30&mkey={r['MENU_ID']}"),
         "thumb_url": f"https://www.kma.or.kr/upload/crs/{r['CRSCD']}/{r['SAVE_FILENM']}" if r.get("SAVE_FILENM") else ""},
        fits, "b2b_title+tag")

# 3) LXP 이러닝 — 소분류 단위 매핑 + 제목 보정
LXP_MAP = {
    ("경영직무", "리더십일반", "조직관리"): [("LEAD-PD", 0.75), ("CHANGE_MG", 0.65)],
    ("경영직무", "리더십일반", "성과관리"): [("LEAD-PD", 0.85)],
    ("경영직무", "리더십일반", "계층리더십"): [("LEAD-PD", 0.7), ("LEAD-CI", 0.65)],
    ("경영직무", "리더십일반", "셀프리더십"): [("CORE-GM", 0.75)],
    ("경영직무", "리더십일반", "문제해결"): [("JOB-PS", 0.85)],
    ("경영직무", "리더십일반", "*"): [("LEAD-PD", 0.65), ("LEAD-CI", 0.65)],
    ("경영직무", "4차산업혁명", "*"): [("AI_USE", 0.8), ("DX_APPLY", 0.7)],
    ("경영직무", "경영일반", "프로젝트 관리"): [("PM_EXEC", 0.85), ("JOB-EX", 0.7)],
    ("경영직무", "경영일반", "R&D"): [("RND_CORE", 0.8)],
    ("경영직무", "경영일반", "*"): [("JOB-ST", 0.5)],
    ("경영직무", "경영전략", "*"): [("JOB-ST", 0.85), ("STRAT_CORE", 0.8)],
    ("공통직무", "비즈니스스킬", "커뮤니케이션"): [("LEAD-CI", 0.8), ("CORE-CL", 0.6)],
    ("공통직무", "비즈니스스킬", "프레젠테이션"): [("COMM_PRES", 0.9)],
    ("공통직무", "비즈니스스킬", "문서작성"): [("COMM_PRES", 0.85)],
    ("공통직무", "비즈니스스킬", "기획/창의"): [("PLAN_STR", 0.85), ("INNOV_ID", 0.7)],
    ("공통직무", "비즈니스스킬", "글로벌이문화"): [("GLOBAL_BZ", 0.8)],
    ("공통직무", "비즈니스스킬", "*"): [("LEAD-CI", 0.6)],
    ("공통직무", "OA", "엑셀"): [("DATA_ANA", 0.7)],
    ("공통직무", "OA", "파워포인트"): [("COMM_PRES", 0.7)],
    ("공통직무", "OA", "*"): [("DATA_ANA", 0.5)],
    ("전문직무", "HR", "*"): [("HR_CORE", 0.9)],
    ("전문직무", "마케팅", "*"): [("MKT_CORE", 0.9)],
    ("전문직무", "회계/재무/세무", "*"): [("FIN_CORE", 0.85)],
    ("전문직무", "법률", "*"): [("LEGAL_CORE", 0.85)],
    ("전문직무", "구매", "*"): [("PROC_CORE", 0.9)],
    ("전문직무", "생산/품질", "*"): [("MFG_CORE", 0.9)],
    ("전문직무", "CS", "*"): [("CORE-CO", 0.85)],
    ("IT", "AI", "*"): [("AI_USE", 0.65), ("DEV_CORE", 0.6)],
    ("IT", "IT 트렌드", "*"): [("DX_APPLY", 0.65)],
    ("IT", "프로그래밍언어", "*"): [("DEV_CORE", 0.85)],
    ("IT", "웹 프로그래밍", "*"): [("DEV_CORE", 0.85)],
    ("IT", "앱 개발", "*"): [("DEV_CORE", 0.85)],
    ("IT", "데이터베이스", "*"): [("DEV_CORE", 0.8), ("DATA_JOB", 0.7)],
}
lxp_kept = lxp_nolink = 0
for r in csv.DictReader(io.open("lxp_to_studio_match.csv", encoding="utf-8-sig")):
    if r["대분류"] in ("자격증", "어학", "법정교육", "인문교양"):
        continue
    key = (r["대분류"], r["중분류"], r["소분류"])
    fits = {code: fit for code, fit in (LXP_MAP.get(key) or LXP_MAP.get((key[0], key[1], "*")) or [])}
    apply(r["lxp_title"], fits)
    fits = finalize(r["lxp_title"], fits)
    if not fits:
        continue
    lxp_kept += 1
    lxp_nolink += not r["eduSeq"]
    # stud.io 링크가 없는 과정은 제목 해시로 ID를 만들어 빌드마다 같은 ID를 유지한다.
    no_link_id = "NA" + hashlib.sha1(r["lxp_title"].encode("utf-8")).hexdigest()[:8]
    add({**BASE, "course_id": f"KMA-LXP-{r['eduSeq'] or no_link_id}", "source": "studio_elearning",
         "title": r["lxp_title"], "delivery": "online", "target_level": level_of(r["lxp_title"]),
         "category": "/".join(key), "has_upcoming": bool(r["eduSeq"]),
         "url": r["url"] or "https://studio.kma.or.kr/member/eLearning", "dev_ym": r["개발년도"]}, fits, "lxp_subcategory+title")

# 4) stud.io 오리지널 — 제목만, 상한 0.6 (보조)
stu_kept = 0
for r in read_csv(INPUTS / "studio_original.csv"):
    fits = {}
    apply(str(r["콘텐츠명"]), fits, cap=0.6)
    fits = finalize(str(r["콘텐츠명"]), fits)
    if not fits:
        continue
    stu_kept += 1
    add({**BASE, "course_id": "KMA-STU-" + str(r["콘텐츠url"]).rsplit("/", 1)[-1], "source": "studio_original",
         "title": str(r["콘텐츠명"]), "delivery": "online_short", "target_level": "all",
         "category": f"{r['대분류']}>{r['중분류']}", "has_upcoming": True, "url": str(r["콘텐츠url"])}, fits, "studio_title")

keys = sorted({k for c in catalog for k in c})
with io.open("kma_course_catalog_v3.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(catalog)
with io.open("kma_competency_course_map_v3.csv", "w", encoding="utf-8-sig", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["factor_code", "course_id", "content_fit", "basis"]); w.writeheader(); w.writerows(mapping)

out = io.open("catalog_v3_summary.txt", "w", encoding="utf-8")
src = collections.Counter(c["source"] for c in catalog)
out.write(f"카탈로그 {len(catalog)}건: {dict(src)}\n오프라인 제외: {dict(excluded)}\n")
out.write(f"LXP 포함 {lxp_kept} (링크 없음 {lxp_nolink}) / stud.io 오리지널 {stu_kept}\n\n역량별 후보 수 (off/b2b/lxp/studio):\n")
per = collections.defaultdict(collections.Counter)
by_id = {c["course_id"]: c for c in catalog}
for m in mapping:
    per[m["factor_code"]][by_id[m["course_id"]]["source"]] += 1
for code in sorted(per):
    p = per[code]
    out.write(f"  {code:12s} off={p['public_edu_center']:3d} b2b={p['b2b_inquiry']:3d} lxp={p['studio_elearning']:3d} studio={p['studio_original']:3d}\n")
out.close()
