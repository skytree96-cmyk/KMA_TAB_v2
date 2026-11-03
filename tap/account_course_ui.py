"""Course cards shared by the participant report and the organization report screens."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import streamlit as st

SOURCE_LABELS = {
    "public_edu_center": "공개교육",
    "studio_elearning": "이러닝",
    "b2b_inquiry": "단체교육 문의",
    "studio_original": "stud.io",
}
BUTTON_LABELS = {
    "public_edu_center": "최신 일정 보기",
    "studio_elearning": "바로 수강",
    "b2b_inquiry": "과정 안내 보기",
}


def render_course_cards(courses: Sequence[Mapping[str, Any]], *, key_prefix: str = "") -> None:
    """Group picks by competency; each competency shows its public course and e-learning side by side."""
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for course in courses:
        groups.setdefault(str(course["factor_code"]), []).append(course)
    for code, rows in groups.items():
        first = rows[0]
        with st.container(border=True):
            st.markdown(f"**{first['factor_name_ko']}** · {first['reason']}")
            if first.get("advice"):
                st.caption(first["advice"])
            columns = st.columns(max(len(rows), 2))  # a lone card keeps half width instead of a giant thumbnail
            for column, course in zip(columns, rows):
                with column:
                    source = str(course.get("source", ""))
                    if course.get("thumb_url"):
                        st.image(str(course["thumb_url"]), width="stretch")
                    st.markdown(f"`{SOURCE_LABELS.get(source, course.get('delivery_label', ''))}` **{course['title']}**")
                    if course.get("schedule"):
                        st.caption(course["schedule"])
                    if course.get("url"):
                        st.link_button(BUTTON_LABELS.get(source, "KMA에서 과정 찾기"), str(course["url"]))
