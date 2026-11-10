"""화면 공통 모양. 색은 .streamlit/config.toml 테마가 정하고, 여기에는 테마로 안 되는 것만 둔다."""

import streamlit as st

_CSS = """
<style>
/* 배경: 위쪽 가운데가 은은하게 보라색으로 번지는 느낌 */
.stApp {
    background: radial-gradient(ellipse 70% 45% at 50% 0%, #E6DAFF 0%, rgba(245, 241, 255, 0) 100%), #F5F1FF;
}
/* 카드: 테두리가 있는 상자와 칸을 반투명 흰색에 부드러운 그림자로 */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {
    background: rgba(255, 255, 255, 0.72);
    box-shadow: 0 4px 18px rgba(123, 79, 223, 0.08);
}
/* 사이드바 메뉴: 지금 보는 페이지를 보라색 알약으로 */
[data-testid="stSidebarNav"] a[aria-current="page"] {
    background: #7B4FDF;
    color: #FFFFFF;
    border-radius: 0.75rem;
}
[data-testid="stSidebarNav"] a[aria-current="page"] * {
    color: #FFFFFF;
}
</style>
"""


def apply():
    """각 페이지 맨 위(set_page_config 바로 다음)에서 한 번 부른다."""
    st.markdown(_CSS, unsafe_allow_html=True)
