"""AI 없이 코드로 처리하는 규칙·판정. 기준은 data/업무설명_하자보수.md.

- 하자대장 읽기·저장 (저장소는 db.py의 DB)
- 접수번호(HJ-YYYYMMDD-NN), 조치기한(긴급 +1일 / 높음 +3일 / 보통 +7일)
- 공사정보 매칭과 보증 판정
- register(대장, AI 결과 목록): 대장에 추가하고 바로 판정
"""

import csv
import re
from datetime import date, timedelta
from pathlib import Path

import db

BASE_DIR = Path(__file__).resolve().parent
LEDGER_PATH = "DB(DATABASE_URL)"  # 하자대장이 저장된 곳
PROJECT_PATH = BASE_DIR / "data" / "공사정보.csv"

COLUMNS = db.LEDGER_COLUMNS  # 업무설명 2번의 열 순서

KINDS = ["방수", "타일", "전기", "설비", "기계", "도장", "바닥재"]  # 업무설명 3번의 공종
URGENCY_DAYS = {"긴급": 1, "높음": 3, "보통": 7}
EXPIRY_SOON_DAYS = 30
UNDECIDED = "미정"
NEEDS_CHECK = "확인필요"


# ---------- 파일 읽기·저장 ----------

def load_projects(path=PROJECT_PATH):
    """공사정보.csv를 읽는다."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_ledger():
    """하자대장을 읽는다. (db.py에 맡긴다. 비어 있으면 빈 목록)"""
    return db.load_ledger()


def save_ledger(ledger):
    """하자대장을 저장한다. (db.py에 맡긴다)"""
    db.save_ledger(ledger)


# ---------- 날짜 ----------

def parse_date(text):
    """'YYYY-MM-DD'를 date로 바꾼다. 형식이 맞지 않으면 None."""
    try:
        return date.fromisoformat(str(text).strip())
    except ValueError:
        return None


def date_from_filename(name):
    """파일 이름 속 8자리 날짜(예: 01_20261102_...)를 date로 바꾼다. 없으면 None."""
    m = re.search(r"(?<!\d)(20\d{2})(\d{2})(\d{2})(?!\d)", name)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def add_years(d, years):
    """준공일 + 보증기간(년). 2월 29일 준공은 해당 연도에 29일이 없으면 2월 28일로 본다."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return date(d.year + years, 2, 28)


# ---------- 접수번호·조치기한 ----------

def make_receipt_no(ledger, receipt_date):
    """HJ-YYYYMMDD-NN. 같은 접수일의 기존 건수 + 1이 순번이다. 접수일을 모르면 HJ-미정-NN."""
    stamp = receipt_date.strftime("%Y%m%d") if receipt_date else UNDECIDED
    prefix = f"HJ-{stamp}-"
    count = sum(1 for row in ledger if row["접수번호"].startswith(prefix))
    return f"{prefix}{count + 1:02d}"


def due_date(receipt_date, urgency):
    """조치기한 = 접수일 + 긴급 1일 / 높음 3일 / 보통 7일. 계산할 수 없으면 None."""
    if receipt_date is None or urgency not in URGENCY_DAYS:
        return None
    return receipt_date + timedelta(days=URGENCY_DAYS[urgency])


# ---------- 보증 판정 ----------

def _describe(project):
    return f"{project['공사번호']} {project['공사명']}({project['공종']}, {project['시공업체']})"


def judge(row, projects):
    """row의 접수일·위치·공종으로 공사를 찾아 보증 판정 칸을 채운다. 비고에는 이유를 덧붙인다.

    판정 기준은 오늘이 아니라 접수일이다. 같은 row에 두 번 부르면 비고가 중복되므로 한 번만 부른다.
    """
    notes = []
    for col in ("공사번호", "시공업체", "준공일", "보증만료일", "보증판정", "책임구분"):
        row[col] = ""

    place, kind = row["위치"].strip(), row["공종"].strip()
    receipt = parse_date(row["접수일"])
    same_place = [p for p in projects if p["위치"].strip() == place]
    matches = [p for p in same_place if p["공종"].strip() == kind]

    reason, candidates = None, []
    if receipt is None:
        reason = "접수일을 알 수 없음"
    elif kind in ("", UNDECIDED):
        reason, candidates = "공종 미정", same_place
    elif place in ("", UNDECIDED):
        reason = "위치 미정"
    elif len(matches) == 0:
        reason, candidates = "맞는 공사 없음", same_place
    elif len(matches) >= 2:
        reason, candidates = f"맞는 공사 {len(matches)}건", matches

    if reason:
        row["보증판정"] = NEEDS_CHECK
        row["책임구분"] = NEEDS_CHECK
        row["상태"] = NEEDS_CHECK
        text = f"{reason}"
        if reason in ("공종 미정", "맞는 공사 없음") or len(matches) >= 2:
            text += " / 후보 공사: " + (", ".join(_describe(p) for p in candidates) or "없음")
        notes.append(text)
    else:
        project = matches[0]
        completed = parse_date(project["준공일"])
        expiry = add_years(completed, int(project["하자보증기간(년)"]))
        row["공사번호"] = project["공사번호"]
        row["시공업체"] = project["시공업체"]
        row["준공일"] = completed.isoformat()
        row["보증만료일"] = expiry.isoformat()
        row["상태"] = "판정완료"
        if receipt <= expiry:  # 만료일 당일 포함
            row["보증판정"], row["책임구분"] = "보증내", "시공업체"
            if (expiry - receipt).days <= EXPIRY_SOON_DAYS:
                notes.append("만료임박")
        else:
            row["보증판정"], row["책임구분"] = "보증만료", "자체보수"

    row["비고"] = " / ".join(x for x in [row["비고"], *notes] if x)
    return row


def rejudge(row, projects, kind):
    """담당자가 현장을 보고 공종을 정한 뒤 다시 판정한다. 이전 비고(AI의 확인필요 이유 등)는 지운다."""
    row["공종"] = kind
    row["비고"] = f"공종 현장 확인 후 {kind}로 확정"
    return judge(row, projects)


# ---------- 등록 ----------

def register(ledger, ai_results, projects=None):
    """AI 결과 목록을 대장에 추가하고 바로 판정한다. 추가된 행 목록을 돌려준다.

    ai_results의 각 항목: AI가 뽑은 값(접수일, 위치, 공종, 하자내용, 긴급도, 확인필요) + 원문파일.
    """
    if projects is None:
        projects = load_projects()
    added = []
    for result in ai_results:
        filename = result.get("원문파일", "")
        receipt = parse_date(result.get("접수일", "")) or date_from_filename(filename)
        urgency = str(result.get("긴급도", "")).strip()
        due = due_date(receipt, urgency)

        row = {col: "" for col in COLUMNS}
        row.update({
            "접수번호": make_receipt_no(ledger, receipt),
            "접수일": receipt.isoformat() if receipt else UNDECIDED,
            "원문파일": filename,
            "위치": str(result.get("위치", "")).strip(),
            "공종": str(result.get("공종", "")).strip(),
            "하자내용": str(result.get("하자내용", "")).strip(),
            "긴급도": urgency,
            "조치기한": due.isoformat() if due else "",
            "비고": str(result.get("확인필요", "")).strip(),
        })
        if due is None:
            row["비고"] = " / ".join(x for x in [row["비고"], "긴급도 확인필요"] if x)
        judge(row, projects)
        ledger.append(row)
        added.append(row)
    return added
