"""하자보수 도구의 담당자 화면 입구. 왼쪽 메뉴: 대시보드(dashboard.py) · 접수입력(intake.py).

실행: python -m streamlit run app.py   (웹에는 intake.py만 올린다)
"""

import streamlit as st

st.set_page_config(page_title="하자보수", layout="wide")

pages = [
    st.Page("dashboard.py", title="대시보드", icon=":material/dashboard:", default=True),
    st.Page("intake.py", title="접수입력", icon=":material/edit_note:"),
]
st.navigation(pages).run()
