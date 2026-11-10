"""접수함 일괄 처리: 대장에 없는 파일만 AI로 정리 → 등록·판정 → 저장 → 결과 표 출력."""

import unicodedata
from pathlib import Path

import ai
import rules

INBOX = Path(__file__).resolve().parent / "data" / "접수함"
SHOW = ["접수번호", "위치", "공종", "긴급도", "조치기한", "보증판정", "책임구분", "상태", "비고"]


def _width(text):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text, width):
    return text + " " * (width - _width(text))


def print_table(rows, columns=SHOW):
    """한글 폭을 맞춰 표로 출력한다."""
    widths = {c: max([_width(c)] + [_width(r[c]) for r in rows]) for c in columns}
    print("  ".join(_pad(c, widths[c]) for c in columns))
    print("  ".join("-" * widths[c] for c in columns))
    for r in rows:
        print("  ".join(_pad(r[c], widths[c]) for c in columns))


def organize(filename, text):
    """원문 1건을 AI로 정리한다. 결과에 원문파일을 붙여 돌려준다. (run.py와 app.py가 함께 쓴다)"""
    message = f"파일 이름: {filename}\n\n원문:\n{text}"
    result = ai.ask_json("접수정리.md", message)
    result["원문파일"] = filename
    return result


def main():
    ledger = rules.load_ledger()
    done = {row["원문파일"] for row in ledger}
    todo = [p for p in sorted(INBOX.glob("*.txt")) if p.name not in done]
    print(f"접수함 {len(list(INBOX.glob('*.txt')))}건 중 새로 처리할 파일 {len(todo)}건")

    results = []
    for path in todo:
        try:
            result = organize(path.name, path.read_text(encoding="utf-8"))
        except RuntimeError as e:  # API 키 문제 등은 전체를 멈춘다
            print(f"\n[중단] {e}")
            raise SystemExit(1)
        except Exception as e:  # 한 건의 실패는 건너뛴다. 대장에 없으므로 다음 실행에서 다시 처리된다.
            print(f"[건너뜀] {path.name}: {e}")
            continue
        results.append(result)
        print(f"[정리] {path.name}")

    rules.register(ledger, results)
    rules.save_ledger(ledger)
    print(f"\n하자대장 {len(ledger)}건 저장: {rules.LEDGER_PATH}\n")
    if ledger:
        print_table(ledger)


if __name__ == "__main__":
    main()
