"""DB 저장소 (SQLAlchemy). 접수와 하자대장을 저장하는 코드는 이 파일에만 둔다.

- 연결 정보: .env(또는 환경변수·Streamlit Secrets)의 DATABASE_URL 한 줄
    Supabase  postgresql://postgres.xxxx:비밀번호@...pooler.supabase.com:5432/postgres  (Session pooler 주소)
    내 PC DB  sqlite:///data/하자보수.db
- 접수 테이블: id, 접수일시, 발견일, 접수자, 부서, 위치, 내용, 사진, 처리상태(미처리/처리완료), 접수번호
- 하자대장 테이블: 업무설명 2번의 16개 열 (접수번호가 기본키)
- 하자대장: load_ledger() / save_ledger(ledger)
- 접수: add_receipt() / load_receipts() / finish_receipt()
- 예전 SQLite(data/하자보수.db)를 DATABASE_URL의 DB로 옮기기: `python db.py` (대상이 비어 있을 때만, 한 번)
"""

import csv
import os
import sqlite3
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (
    CheckConstraint, Column, Integer, MetaData, String, Table, Text, create_engine, delete, insert, select, text,
    update,
)

BASE_DIR = Path(__file__).resolve().parent
OLD_SQLITE_PATH = BASE_DIR / "data" / "하자보수.db"  # 예전(7단계 SQLite) 저장소. 옮길 때만 쓴다.
CSV_PATH = BASE_DIR / "data" / "하자대장.csv"

# 업무설명 2번의 열 순서
LEDGER_COLUMNS = [
    "접수번호", "접수일", "원문파일", "위치", "공종", "하자내용", "긴급도", "조치기한",
    "공사번호", "시공업체", "준공일", "보증만료일", "보증판정", "책임구분", "상태", "비고",
]
RECEIPT_COLUMNS = [
    "id", "접수일시", "발견일", "접수자", "부서", "위치", "내용", "사진", "처리상태", "접수번호",
]
RECEIPT_FIELDS = RECEIPT_COLUMNS[1:]  # id는 DB가 매긴다
RECEIPT_STATES = ("미처리", "처리완료")

metadata = MetaData()
receipts = Table(
    "접수", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    *[Column(c, Text, nullable=False, server_default="" if c != "처리상태" else "미처리") for c in RECEIPT_FIELDS],
    CheckConstraint("처리상태 IN ('미처리', '처리완료')", name="접수_처리상태_check"),
)
ledger_table = Table(
    "하자대장", metadata,
    Column("접수번호", String(40), primary_key=True),
    *[Column(c, Text, nullable=False, server_default="") for c in LEDGER_COLUMNS[1:]],
)

_engine = None


def _database_url():
    load_dotenv(BASE_DIR / ".env")
    url = (os.environ.get("DATABASE_URL") or "").strip().strip("\"'")
    if not url:
        raise RuntimeError(
            "DB 연결 정보(DATABASE_URL)가 없습니다. .env에 DATABASE_URL=… 한 줄을 넣거나, "
            "웹에서는 Streamlit Secrets에 DATABASE_URL = \"…\" 를 넣으세요. "
            "(내 PC DB로 쓰려면 sqlite:///data/하자보수.db)"
        )
    for old in ("postgresql://", "postgres://"):  # 드라이버(psycopg)를 지정한다
        if url.startswith(old):
            return "postgresql+psycopg://" + url[len(old):]
    if url.startswith("sqlite:///"):
        rest = url[len("sqlite:///"):]
        if rest and not rest.startswith(("/", ":")) and not Path(rest).is_absolute():
            return "sqlite:///" + (BASE_DIR / rest).as_posix()  # 상대 경로는 프로젝트 기준
    return url


def get_engine():
    """DATABASE_URL로 연결을 만들고, 테이블이 없으면 만든다. (한 번만)"""
    global _engine
    if _engine is None:
        engine = create_engine(_database_url(), pool_pre_ping=True)
        metadata.create_all(engine)
        if engine.dialect.name == "postgresql":  # Supabase: 공개 API(anon 키)로 못 읽게 RLS를 켠다
            with engine.begin() as conn:
                for table in (receipts, ledger_table):
                    conn.execute(text(f'ALTER TABLE "{table.name}" ENABLE ROW LEVEL SECURITY'))
        _engine = engine
    return _engine


def reset_engine():
    """연결을 닫는다. (DATABASE_URL을 바꾼 뒤 다시 읽게 할 때)"""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


# ---------- 하자대장 ----------

def load_ledger():
    """하자대장을 접수번호 순서로 읽는다. 행마다 LEDGER_COLUMNS를 키로 가진 딕셔너리."""
    with get_engine().connect() as conn:
        rows = conn.execute(select(ledger_table).order_by(ledger_table.c.접수번호)).mappings().all()
    return [{c: row[c] for c in LEDGER_COLUMNS} for row in rows]


def save_ledger(ledger):
    """하자대장 전체를 저장한다. 한 번의 트랜잭션이라 중간에 실패하면 이전 내용이 그대로 남는다."""
    values = [{c: str(row.get(c, "") or "") for c in LEDGER_COLUMNS} for row in ledger]
    with get_engine().begin() as conn:
        conn.execute(delete(ledger_table))
        if values:
            conn.execute(insert(ledger_table), values)


# ---------- 접수 ----------

def add_receipt(receipt):
    """접수 1건을 저장하고 id를 돌려준다. 접수일시를 안 주면 지금 시각, 처리상태를 안 주면 미처리."""
    row = {c: str(receipt.get(c, "") or "") for c in RECEIPT_FIELDS}
    row["접수일시"] = row["접수일시"] or datetime.now().isoformat(timespec="seconds")
    row["처리상태"] = row["처리상태"] or "미처리"
    with get_engine().begin() as conn:
        result = conn.execute(insert(receipts).values(**row))
        return result.inserted_primary_key[0]


def load_receipts(limit=None, newest_first=False):
    """접수를 id 순서로 읽는다. newest_first=True면 최신이 앞, limit이 있으면 그 건수만."""
    query = select(receipts).order_by(receipts.c.id.desc() if newest_first else receipts.c.id)
    if limit is not None:
        query = query.limit(int(limit))
    with get_engine().connect() as conn:
        rows = conn.execute(query).mappings().all()
    return [{c: row[c] for c in RECEIPT_COLUMNS} for row in rows]


def finish_receipt(receipt_id, receipt_no):
    """접수를 처리완료로 바꾸고 하자대장의 접수번호를 적는다. 없는 id면 False."""
    with get_engine().begin() as conn:
        result = conn.execute(
            update(receipts).where(receipts.c.id == int(receipt_id)).values(처리상태="처리완료", 접수번호=receipt_no)
        )
    return result.rowcount == 1


# ---------- 옮기기 ----------

def counts():
    """테이블별 건수. {'접수': n, '하자대장': n}"""
    with get_engine().connect() as conn:
        return {t.name: conn.execute(select(text("count(*)")).select_from(t)).scalar() for t in (receipts, ledger_table)}


def import_sqlite(path=OLD_SQLITE_PATH):
    """예전 SQLite(접수·하자대장)를 DATABASE_URL의 DB로 한 번 옮기고 건수를 돌려준다. 대상에 내용이 있으면 멈춘다."""
    if any(counts().values()):
        raise RuntimeError("대상 DB에 이미 내용이 있어 옮기지 않습니다. (덮어쓰기 방지)")
    src = sqlite3.connect(f"file:{Path(path).as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    try:
        ledger_rows = [dict(r) for r in src.execute("SELECT * FROM 하자대장 ORDER BY rowid")]
        receipt_rows = [dict(r) for r in src.execute("SELECT * FROM 접수 ORDER BY id")]
    finally:
        src.close()
    save_ledger(ledger_rows)
    engine = get_engine()
    with engine.begin() as conn:
        if receipt_rows:
            conn.execute(insert(receipts), receipt_rows)  # id를 그대로 옮긴다
        if engine.dialect.name == "postgresql":  # 다음 접수가 옮긴 id와 겹치지 않게 번호표를 맞춘다
            conn.execute(text(
                "SELECT setval(pg_get_serial_sequence('\"접수\"', 'id'), COALESCE((SELECT MAX(id) FROM \"접수\"), 1))"
            ))
    return {"하자대장": len(ledger_rows), "접수": len(receipt_rows)}


def import_csv(path=CSV_PATH):
    """예전 하자대장.csv를 DB로 한 번 옮기고 옮긴 건수를 돌려준다. 대장에 이미 내용이 있으면 멈춘다."""
    if load_ledger():
        raise RuntimeError("하자대장 테이블에 이미 내용이 있어 옮기지 않습니다. (덮어쓰기 방지)")
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = [{c: (row.get(c) or "") for c in LEDGER_COLUMNS} for row in csv.DictReader(f)]
    save_ledger(rows)
    return len(rows)


if __name__ == "__main__":
    moved = import_sqlite() if OLD_SQLITE_PATH.exists() else {"하자대장": import_csv(), "접수": 0}
    print(f"옮긴 건수: 하자대장 {moved['하자대장']}건, 접수 {moved['접수']}건")
    print(f"DB 현재 건수: {counts()}")
