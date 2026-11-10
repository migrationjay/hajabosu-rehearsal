"""하자보수 담당자 화면(대시보드 페이지). app.py의 메뉴에서 열린다. 계산·판정은 rules.py, AI 정리는 run.organize(ai.py)를 그대로 쓴다."""

import io
from datetime import date

import pandas as pd
import streamlit as st

import db
import report
import rules
import run
import style

INBOX = run.INBOX
DRAFT_COLS = ["원문파일", "접수일", "위치", "공종", "하자내용", "긴급도", "확인필요"]
KIND_OPTIONS = rules.KINDS + [rules.UNDECIDED]
URGENCY_OPTIONS = list(rules.URGENCY_DAYS)
STATES = ["접수", "판정완료", "확인필요", "조치요청"]

style.apply()
st.title("하자보수 접수")

ledger = rules.load_ledger()
projects = rules.load_projects()
done_files = {row["원문파일"] for row in ledger}

if "draft" not in st.session_state:
    st.session_state.draft = pd.DataFrame(columns=DRAFT_COLS)  # 정리 결과(고치는 중인 표)
    st.session_state.texts = {}  # 원문파일 이름 -> 원문 글
    st.session_state.receipt_ids = {}  # 원문파일 이름 -> DB 접수 id (DB 접수에서 온 것만)

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))


# ---------- 도우미 ----------

def organize_files(items):
    """[(파일 이름, 원문)] 을 AI로 정리해 정리 결과 표에 더한다."""
    rows, errors = [], []
    with st.spinner("AI가 정리하는 중입니다..."):
        for name, text in items:
            try:
                result = run.organize(name, text)
            except RuntimeError as e:  # API 키 문제 등은 전체를 멈춘다
                st.error(str(e))
                return
            except Exception as e:
                errors.append(f"{name}: {e}")
                continue
            st.session_state.texts[name] = text
            rows.append({c: str(result.get(c, "") or "") for c in DRAFT_COLS})
    for message in errors:
        st.error(f"정리하지 못했습니다. {message}")
    if rows:
        old = st.session_state.draft
        keep = old[~old["원문파일"].isin([r["원문파일"] for r in rows])]
        st.session_state.draft = pd.concat([keep, pd.DataFrame(rows)], ignore_index=True)
        st.session_state.pop("draft_editor", None)  # 표를 새로 그린다
        st.rerun()


def read_upload(file):
    data = file.getvalue()
    for encoding in ("utf-8-sig", "cp949"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def next_paste_name():
    """붙여넣은 글의 파일 이름. 8자리 숫자를 넣지 않는다(파일명 날짜로 접수일을 잘못 채우지 않으려고)."""
    used = done_files | {p.name for p in INBOX.glob("*.txt")} | set(st.session_state.draft["원문파일"])
    n = 1
    while f"붙여넣기_{n}.txt" in used:
        n += 1
    return f"붙여넣기_{n}.txt"


def receipt_file_name(receipt_id):
    """DB 접수를 AI에 넘길 때 쓰는 원문파일 이름. 8자리 숫자를 넣지 않는다(파일명 날짜로 접수일을 채우지 않으려고)."""
    return f"접수_{receipt_id}.txt"


def receipt_text(r):
    """DB 접수 1건을 현장 메모 모양의 글로 바꾼다. 발견일이 글의 날짜가 된다."""
    who = f"{r['접수자']} ({r['부서']})" if r["부서"] else r["접수자"]
    return f"[현장 접수] {r['발견일']}\n접수자: {who}\n위치: {r['위치']}\n\n{r['내용']}"


def register_draft(edited):
    """고친 표를 대장에 등록하고 바로 보증 판정한다. DB 접수에서 온 건은 처리완료와 접수번호로 바꾼다."""
    results = edited.fillna("").astype(str).to_dict("records")
    results = [r for r in results if r["원문파일"] not in done_files]
    receipt_ids = st.session_state.receipt_ids
    for r in results:  # 붙여넣기·올린 파일은 원문을 접수함에 새 파일로 남긴다(기존 파일은 덮어쓰지 않는다)
        if r["원문파일"] in receipt_ids:  # DB 접수의 원문은 DB에 있다
            continue
        path = INBOX / r["원문파일"]
        if not path.exists():
            path.write_text(st.session_state.texts.get(r["원문파일"], ""), encoding="utf-8")
    added = rules.register(ledger, results, projects)
    rules.save_ledger(ledger)
    finished = 0
    for row in added:
        receipt_id = receipt_ids.get(row["원문파일"])
        if receipt_id is not None and db.finish_receipt(receipt_id, row["접수번호"]):
            finished += 1
    st.session_state.draft = pd.DataFrame(columns=DRAFT_COLS)
    st.session_state.pop("draft_editor", None)
    st.session_state.flash = f"{len(added)}건을 대장에 등록하고 보증 판정했습니다." + (
        f" DB 접수 {finished}건은 처리완료로 바꿨습니다." if finished else ""
    )
    st.rerun()


def show_files(pattern, label, key, as_code=False):
    """output 폴더의 결과물을 골라 미리보고 내려받는다."""
    files = sorted(report.OUTPUT_DIR.glob(pattern), reverse=True)
    if not files:
        st.caption("아직 만든 파일이 없습니다.")
        return
    chosen = st.selectbox(label, files, format_func=lambda p: p.name, key=f"pick_{key}")
    text = chosen.read_text(encoding="utf-8")
    with st.container(border=True):
        if as_code:
            st.code(text, language=None)
        else:
            st.markdown(text)
    st.download_button(
        f"{chosen.name} 내려받기", data=chosen.read_bytes(), file_name=chosen.name, key=f"dl_{key}",
    )


# ---------- 맨 위: 건수 ----------

c1, c2, c3, c4 = st.columns(4, border=True)
c1.metric("전체", len(ledger))
c2.metric("긴급", sum(r["긴급도"] == "긴급" for r in ledger))
c3.metric("확인필요", sum(r["상태"] == "확인필요" for r in ledger))
c4.metric("조치요청", sum(r["상태"] == "조치요청" for r in ledger))

tab1, tab2, tab3, tab4 = st.tabs(["접수 등록", "처리 현황", "하자대장", "조치·보고"])

# ---------- 탭1 접수 등록 ----------

with tab1:
    left, right = st.columns(2, border=True)

    with left:
        st.subheader("DB의 미처리 접수")
        st.caption("현장 직원이 접수 입력 화면에서 올린 접수입니다.")
        if st.button("새 접수 불러오기", key="reload_receipts"):
            st.rerun()  # DB를 다시 읽는다
        pending = {
            r["id"]: r
            for r in db.load_receipts()
            if r["처리상태"] == "미처리" and receipt_file_name(r["id"]) not in done_files
        }
        if not pending:
            st.info("미처리 접수가 없습니다.")
        else:
            chosen = st.multiselect(
                "정리할 접수",
                list(pending),
                default=list(pending),
                format_func=lambda i: (
                    f"#{i} {pending[i]['발견일']} {pending[i]['접수자']} · {pending[i]['위치']} · {pending[i]['내용'][:20]}"
                ),
            )
            if st.button("AI로 정리", key="organize_receipts", disabled=not chosen):
                items = []
                for i in chosen:
                    name = receipt_file_name(i)
                    st.session_state.receipt_ids[name] = i
                    items.append((name, receipt_text(pending[i])))
                organize_files(items)

    with right:
        st.subheader("메일·메모 붙여넣기 또는 txt 올리기")
        pasted = st.text_area("원문", height=150, key="paste_text")
        uploads = st.file_uploader("txt 파일", type="txt", accept_multiple_files=True, key="uploads")
        if st.button("AI로 정리", key="organize_paste"):
            items, taken = [], set()
            if pasted.strip():
                items.append((next_paste_name(), pasted))
            for f in uploads:
                if f.name in done_files or f.name in taken:
                    st.warning(f"{f.name}은(는) 이미 대장에 있거나 중복이라 건너뜁니다.")
                    continue
                taken.add(f.name)
                items.append((f.name, read_upload(f)))
            if items:
                organize_files(items)
            else:
                st.warning("붙여넣은 글이나 올린 파일이 없습니다.")

    draft = st.session_state.draft
    if not draft.empty:
        st.divider()
        st.subheader("정리 결과")
        st.caption("틀린 값은 표에서 바로 고친 뒤 등록하세요. 접수번호·조치기한·보증 판정은 등록할 때 코드가 계산합니다.")
        draft = draft.copy()
        draft["공종"] = draft["공종"].where(draft["공종"].isin(KIND_OPTIONS), rules.UNDECIDED)
        draft["긴급도"] = draft["긴급도"].where(draft["긴급도"].isin(URGENCY_OPTIONS), None)
        edited = st.data_editor(
            draft,
            key="draft_editor",
            hide_index=True,
            width="stretch",
            disabled=["원문파일"],
            column_config={
                "공종": st.column_config.SelectboxColumn(options=KIND_OPTIONS),
                "긴급도": st.column_config.SelectboxColumn(options=URGENCY_OPTIONS),
            },
        )
        if st.button("대장에 등록", type="primary"):
            register_draft(edited)

# ---------- 탭2 처리 현황 ----------

with tab2:
    cols = st.columns(len(STATES))
    for state, col in zip(STATES, cols):
        rows = [r for r in ledger if r["상태"] == state]
        with col, st.container(border=True):
            st.subheader(state)
            st.metric("건수", len(rows))
            for r in rows:
                st.markdown(f"**{r['접수번호']}** · {r['위치']} · {r['공종']}")
                st.caption(f"{r['하자내용']} (조치기한 {r['조치기한']})")

# ---------- 탭3 하자대장 ----------

with tab3:
    if not ledger:
        st.info("대장이 비어 있습니다. '접수 등록' 탭에서 접수를 등록하세요.")
    else:
        table = pd.DataFrame(ledger, columns=rules.COLUMNS)
        st.dataframe(table, hide_index=True, width="stretch")

        buffer = io.BytesIO()
        table.to_excel(buffer, index=False, engine="openpyxl")
        st.download_button(
            "엑셀 내려받기",
            data=buffer.getvalue(),
            file_name="하자대장.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        needs = [(i, r) for i, r in enumerate(ledger) if r["상태"] == "확인필요"]
        if needs:
            st.divider()
            st.subheader("확인필요 건 다시 판정")
            st.caption("현장을 확인한 뒤 공종을 고르고 [다시 판정]을 누르세요.")
            for i, row in needs:
                with st.container(border=True):
                    st.markdown(f"**{row['접수번호']}** · {row['위치']} · {row['하자내용']}")
                    st.caption(row["비고"])
                    a, b = st.columns([3, 1])
                    kind = a.selectbox(
                        "공종", rules.KINDS, index=None, placeholder="공종 선택",
                        key=f"kind_{i}", label_visibility="collapsed",
                    )
                    if b.button("다시 판정", key=f"rejudge_{i}", disabled=kind is None):
                        rules.rejudge(row, projects, kind)
                        rules.save_ledger(ledger)
                        st.session_state.flash = f"{row['접수번호']}을(를) {kind}로 다시 판정했습니다. → {row['보증판정']}"
                        st.rerun()

# ---------- 탭4 조치·보고 ----------

with tab4:
    st.subheader("업체 공문·조치일정")
    waiting = [r for r in ledger if r["상태"] == report.PENDING]
    to_vendor = [r for r in waiting if r["책임구분"] == "시공업체"]
    st.write(f"판정완료 {len(waiting)}건 (업체 요청 {len(to_vendor)}건, 자체보수 {len(waiting) - len(to_vendor)}건)")
    st.caption("공문은 업체별 1개, 조치일정은 판정완료 건의 조치기한입니다. 만들면 이 건들의 상태가 조치요청으로 바뀝니다.")
    if st.button("공문·일정 만들기", disabled=not waiting):
        result = report.request_actions(ledger, projects)
        rules.save_ledger(ledger)
        st.session_state.flash = (
            f"공문 {len(result['공문'])}개와 조치일정을 만들고, {result['건수']}건을 조치요청으로 바꿨습니다."
        )
        st.rerun()
    show_files("공문_*.md", "공문", "letter")
    show_files(report.ICS_NAME, "조치일정", "ics", as_code=True)

    st.divider()
    st.subheader("주간보고")
    base_date = st.date_input("보고 기준일", value=date.today())
    if st.button("주간보고 만들기", disabled=not ledger):
        try:
            with st.spinner("AI가 요약을 쓰는 중입니다..."):
                path = report.write_report(ledger, base_date)
        except RuntimeError as e:  # API 키 문제
            st.error(str(e))
        except Exception as e:
            st.error(f"주간보고를 만들지 못했습니다. {e}")
        else:
            st.session_state.flash = f"{path.name}을(를) 만들었습니다."
            st.rerun()
    show_files("하자현황_주간보고_*.md", "주간보고", "weekly")
