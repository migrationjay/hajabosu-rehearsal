"""입점 매장·현장 직원용 접수 화면. 8단계에서 이 파일만 웹에 올린다.

접수는 db.py로 접수 테이블에 미처리로 저장한다. 다른 사람의 접수 내용은 보여주지 않고 접수 번호만 안내한다.
(rules.py·ai.py는 부르지 않는다. 위치 목록은 data/공사정보.csv를 직접 읽는다.)
"""

import csv
from datetime import date
from pathlib import Path

import streamlit as st

import db

PROJECT_CSV = Path(__file__).resolve().parent / "data" / "공사정보.csv"
OTHER = "기타"

try:  # 담당자 화면(app.py)의 메뉴 안에서 열릴 때는 app.py가 이미 설정했다
    st.set_page_config(page_title="하자 접수", layout="centered")
except st.errors.StreamlitAPIException:
    pass


@st.cache_data
def load_places():
    with open(PROJECT_CSV, encoding="utf-8-sig", newline="") as f:
        return list(dict.fromkeys(row["위치"].strip() for row in csv.DictReader(f))) + [OTHER]


st.title("하자 접수")
st.caption("현장에서 발견한 하자를 입력하고 [접수]를 누르세요. 담당자가 확인해 처리합니다.")

for key in ("in_name", "in_dept", "in_other", "in_text"):
    st.session_state.setdefault(key, "")


def submit():
    """[접수] 버튼: 접수자·위치·내용이 비면 저장하지 않고 안내, 아니면 미처리로 저장."""
    state = st.session_state
    name, text = state.in_name.strip(), state.in_text.strip()
    place = state.in_other.strip() if state.get("in_place") == OTHER else (state.get("in_place") or "")
    missing = [label for label, value in (("접수자", name), ("위치", place), ("내용", text)) if not value]
    if missing:
        state.in_msg = ("warning", f"{', '.join(missing)} 입력이 필요합니다. 아직 저장하지 않았습니다.")
        return
    try:
        receipt_id = db.add_receipt({
            "발견일": state.in_date.isoformat(),
            "접수자": name,
            "부서": state.in_dept.strip(),
            "위치": place,
            "내용": text,
        })
    except Exception as e:
        state.in_msg = ("error", f"저장하지 못했습니다. 잠시 뒤 다시 시도하세요. ({type(e).__name__})")
        return
    state.in_msg = ("success", f"접수했습니다. 접수 번호는 {receipt_id}번입니다. 담당자가 확인해 처리합니다.")
    state.in_place = None  # 다음 접수를 위해 위치·내용은 비우고 접수자·부서·발견일은 남겨 둔다
    state.in_other = ""
    state.in_text = ""


with st.container(border=True):
    st.date_input("발견일", value=date.today(), max_value=date.today(), key="in_date")
    st.text_input("접수자", key="in_name")
    st.text_input("부서·매장", key="in_dept")
    st.selectbox("위치", load_places(), index=None, placeholder="위치 선택", key="in_place")
    if st.session_state.get("in_place") == OTHER:
        st.text_input("위치 직접 입력", placeholder="예: 3F 푸드코트", key="in_other")
    st.text_area("내용", height=140, key="in_text")
    st.button("접수", type="primary", on_click=submit)

    if "in_msg" in st.session_state:
        kind, message = st.session_state.pop("in_msg")
        getattr(st, kind)(message)
