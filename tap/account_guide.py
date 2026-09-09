"""Operating instructions for the account-based service."""
import streamlit as st
from tap.brand import brand_css, brand_html
from tap.account_theme import account_theme_css


def render_account_guide():
    st.html(brand_css() + account_theme_css())
    with st.container(key="tap_guide_shell"):
        with st.container(key="tap_guide_header"):
            st.markdown(brand_html(), unsafe_allow_html=True)
            st.title("이용 안내")
            st.markdown("[로그인하기](/login)")

        with st.container(border=True, key="tap_guide_first_login"):
            st.subheader("처음 로그인할 때")
            st.write("발급받은 로그인 ID 전체와 임시 비밀번호를 입력하세요. 교육담당자는 지정 ID를, 참여자는 발급받은 ID를 그대로 사용합니다. 이메일은 필요하지 않습니다. 처음 접속하면 본인만 아는 3~128자의 비밀번호로 바꾼 뒤 이용할 수 있습니다.")

            st.write("로그인 후 화면 상단 메뉴로 업무 화면을 이동합니다. 우측 상단 프로필을 열면 비밀번호 변경과 로그아웃을 이용할 수 있습니다.")

        roles = [
            ("kma", "KMA 관리자", "회원사의 사업자등록번호 10자리를 등록하고 해당 회사의 교육담당자 계정을 발급합니다. 교육담당자 임시 비밀번호는 kma이며 첫 로그인 때 변경합니다. 회사별 프로젝트와 참여 현황을 확인할 수 있습니다."),
            ("company", "교육담당자", "교육 일정과 측정역량을 정해 프로젝트를 만듭니다. 참여자 계정을 단건 또는 CSV로 발급하고 프로젝트에 배정합니다. 부서·직급·이메일·연락처를 함께 저장할 수 있습니다. user001 같은 기본 예시 ID에는 회사 식별정보가 붙고 직접 정한 ID는 그대로 사용합니다. 임시 비밀번호는 kma입니다. 발급한 로그인 정보를 해당 참여자에게 전달하고 전달 완료 버튼을 누르세요."),
            ("participant", "참여자", "로그인하면 배정된 교육이 표시됩니다. 교육이 여러 개라면 참여할 교육을 선택하세요. 검사 기간에 사전검사를 마치고, 교육 후 사후검사에 참여하면 본인의 변화를 볼 수 있습니다."),
        ]
        role_menus = {
            "kma": "대시보드 · 회원사 · 계정 관리 · 프로젝트 · 문항은행·검수",
            "company": "대시보드 · 프로젝트 · 프로젝트 만들기 · 참여자 계정",
            "participant": "내 교육",
        }
        with st.container(key="tap_guide_roles"):
            for column, (role, title, description) in zip(st.columns(3), roles):
                with column:
                    with st.container(border=True, key=f"tap_guide_role_{role}"):
                        st.subheader(title)
                        st.write(description)
                        st.caption("상단 메뉴: " + role_menus[role])

        with st.container(border=True, key="tap_guide_results"):
            st.subheader("검사 결과 저장과 비교")
            st.write("응답 저장이 확인된 문항부터 이어서 참여할 수 있습니다. 사전·사후 결과는 같은 계정의 같은 프로젝트 배정에 연결됩니다. 사전 결과를 파일로 옮기거나 프로젝트 코드를 입력할 필요가 없습니다. 최종 제출을 마친 응답은 수정할 수 없습니다.")
            st.write("다른 교육의 응답은 별도로 저장됩니다. 프로젝트 배정을 해제해도 기존 검사 결과는 남습니다. 교육담당자에게는 참여 현황과 유효한 전·후 응답이 5명 이상인 역량의 조직 변화가 표시됩니다.")

        with st.container(border=True, key="tap_guide_password"):
            st.subheader("비밀번호를 잊었을 때")
            st.write("참여자는 교육담당자에게, 교육담당자는 KMA 관리자에게 재발급을 요청하세요. 기존 비밀번호를 조회하는 대신 새 임시 비밀번호를 발급합니다. 재발급 또는 계정 사용 중지 시 기존 로그인은 종료됩니다.")
