"""조치·보고 결과물 만들기: 업체 공문(.md), 조치일정(.ics), 주간보고(.md).

표와 계산은 코드가 만들고, 주간보고의 요약 글만 ai.ask("보고작성.md")로 받는다.
"""

import csv
import io
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import ai
import rules

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
ICS_NAME = "조치일정.ics"

PENDING = "판정완료"  # 아직 조치를 요청하지 않은 건
REQUESTED = "조치요청"


def _cell(text):
    """마크다운 표 칸에 넣을 글. 칸을 깨는 글자를 바꾼다."""
    return str(text).replace("|", "/").replace("\n", " ").strip()


def md_table(rows, columns):
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join("---" for _ in columns) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(_cell(r.get(c, "")) for c in columns) + " |")
    return "\n".join(lines)


# ---------- 업체 공문 ----------

def build_letters(rows, projects, today):
    """책임구분이 시공업체인 건을 업체별 공문 글로 만든다. {업체명: 마크다운}"""
    names = {p["공사번호"]: p["공사명"] for p in projects}
    by_vendor = {}
    for r in rows:
        if r["책임구분"] == "시공업체" and r["시공업체"]:
            by_vendor.setdefault(r["시공업체"], []).append(r)

    letters = {}
    for vendor, items in by_vendor.items():
        table_rows = [dict(r, 공사명=names.get(r["공사번호"], "")) for r in items]
        table = md_table(
            table_rows,
            ["접수번호", "위치", "하자내용", "접수일", "조치기한", "공사번호", "공사명", "보증만료일"],
        )
        soon = [r["접수번호"] for r in items if "만료임박" in r["비고"]]
        lines = [
            "# 하자보수 요청 공문",
            "",
            f"- 수신: {vendor} 귀중",
            "- 발신: 시설관리팀",
            f"- 일자: {today.isoformat()}",
            "- 제목: 하자보수 요청의 건",
            "",
            "1. 귀사가 시공한 아래 공사에서 하자가 확인되어, 하자보증기간 내 보수를 요청함.",
            "",
            "2. 하자 내역",
            "",
            table,
            "",
            "3. 위 하자는 표의 조치기한까지 보수하고, 보수 일정을 회신하여 주시기 바람.",
        ]
        if soon:
            lines += ["", f"4. 보증만료일이 임박한 건({', '.join(soon)})은 만료 전에 보수를 요청함."]
        lines += ["", "끝."]
        letters[vendor] = "\n".join(lines) + "\n"
    return letters


# ---------- 조치일정 (.ics) ----------

def _ics_escape(text):
    return str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _ics_fold(line):
    """한 줄이 75바이트를 넘으면 접는다(다음 줄은 공백으로 시작). 글자 중간에서 자르지 않는다."""
    if len(line.encode("utf-8")) <= 75:
        return [line]
    out, cur, size = [], "", 0
    for ch in line:
        n = len(ch.encode("utf-8"))
        if size + n > (75 if not out else 74):
            out.append(cur if not out else " " + cur)
            cur, size = "", 0
        cur += ch
        size += n
    out.append(cur if not out else " " + cur)
    return out


def build_ics(rows, now=None):
    """조치기한을 종일 일정으로 담은 .ics 글. 조치기한이 없는 건은 뺀다."""
    now = now or datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//hajabosu//KO", "CALSCALE:GREGORIAN"]
    for r in rows:
        due = rules.parse_date(r["조치기한"])
        if due is None:
            continue
        who = f"시공업체({r['시공업체']})" if r["책임구분"] == "시공업체" else r["책임구분"]
        summary = f"[{r['긴급도']}] {r['접수번호']} {r['위치']} {r['하자내용']} 조치"
        description = f"책임구분: {who} / 공종: {r['공종']} / 접수일: {r['접수일']}"
        lines += [
            "BEGIN:VEVENT",
            f"UID:{r['접수번호']}@hajabosu",
            f"DTSTAMP:{stamp}",
            f"DTSTART;VALUE=DATE:{due.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(due + timedelta(days=1)).strftime('%Y%m%d')}",
            f"SUMMARY:{_ics_escape(summary)}",
            f"DESCRIPTION:{_ics_escape(description)}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    folded = [piece for line in lines for piece in _ics_fold(line)]
    return "\r\n".join(folded) + "\r\n"


def request_actions(ledger, projects, today=None, out_dir=OUTPUT_DIR):
    """판정완료 건으로 공문과 조치일정을 만들고, 그 건의 상태를 조치요청으로 바꾼다.

    ledger의 상태를 직접 바꾸므로 부른 쪽에서 rules.save_ledger로 저장한다.
    돌려주는 값: {"공문": [파일 경로], "일정": 파일 경로 또는 None, "건수": 조치요청으로 바뀐 건수}
    """
    today = today or date.today()
    out_dir = Path(out_dir)
    targets = [r for r in ledger if r["상태"] == PENDING]
    if not targets:
        return {"공문": [], "일정": None, "건수": 0}
    out_dir.mkdir(parents=True, exist_ok=True)

    letter_paths = []
    for vendor, text in build_letters(targets, projects, today).items():
        path = out_dir / f"공문_{vendor}.md"
        path.write_text(text, encoding="utf-8")
        letter_paths.append(path)

    ics_path = None
    ics_text = build_ics(targets)
    if "BEGIN:VEVENT" in ics_text:
        ics_path = out_dir / ICS_NAME
        ics_path.write_bytes(ics_text.encode("utf-8"))

    for r in targets:
        r["상태"] = REQUESTED
    return {"공문": letter_paths, "일정": ics_path, "건수": len(targets)}


# ---------- 주간보고 ----------

def ledger_csv_text(ledger):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=rules.COLUMNS, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(ledger)
    return buffer.getvalue()


def summarize(ledger, base_date):
    """주간보고의 요약 글(결론·우선 조치·담당자 확인 필요)을 AI에게 받는다."""
    message = f"보고 기준일: {base_date.isoformat()}\n\n하자대장:\n{ledger_csv_text(ledger)}"
    return ai.ask("보고작성.md", message).strip()


def build_report(ledger, summary, base_date):
    """첫 줄 결론 + AI 요약 + 긴급 / 업체 요청 / 자체보수 / 확인필요 표(코드가 만듦)."""
    conclusion, rest = "", summary
    lines = summary.splitlines()
    for i, line in enumerate(lines):
        if line.strip().startswith("결론:"):
            conclusion = line.strip()
            rest = "\n".join(lines[:i] + lines[i + 1 :]).strip()
            break
    if not conclusion:
        conclusion = "결론: (요약에서 결론을 찾지 못함)"

    for title in ("우선 조치", "담당자 확인 필요"):
        rest = "\n".join(f"## {title}" if x.strip() == title else x for x in rest.splitlines())

    out = [conclusion, "", f"보고 기준일: {base_date.isoformat()}", ""]
    if rest:
        out += [rest, ""]

    common = ["접수번호", "위치", "공종", "하자내용", "조치기한", "시공업체", "상태"]
    sections = [
        ("긴급 건", [r for r in ledger if r["긴급도"] == "긴급"], common),
        ("업체 요청 건", [r for r in ledger if r["책임구분"] == "시공업체"], common + ["보증만료일"]),
        ("자체보수 건", [r for r in ledger if r["책임구분"] == "자체보수"], common),
        ("확인필요 건", [r for r in ledger if r["상태"] == rules.NEEDS_CHECK], common + ["비고"]),
    ]
    for title, rows, columns in sections:
        out += [f"## {title} ({len(rows)}건)", ""]
        out += [md_table(rows, columns) if rows else "해당 없음", ""]
    return "\n".join(out)


def write_report(ledger, base_date, out_dir=OUTPUT_DIR):
    """요약을 AI에게 받아 주간보고를 만들고 output/하자현황_주간보고_날짜.md로 저장한다."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    text = build_report(ledger, summarize(ledger, base_date), base_date)
    path = out_dir / f"하자현황_주간보고_{base_date.isoformat()}.md"
    path.write_text(text, encoding="utf-8")
    return path
