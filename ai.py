"""Claude API 호출은 이 파일에서만 한다.

- ask(지침파일, 입력): 지침 폴더의 파일을 시스템 프롬프트로, 입력을 사용자 메시지로 보내고 답변 글을 돌려준다.
- ask_json(지침파일, 입력): 답변에서 JSON만 꺼내 딕셔너리로 돌려준다.
"""

import json
import os
import re
from pathlib import Path

import anthropic
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
GUIDE_DIR = BASE_DIR / "지침"
DEFAULT_MODEL = "claude-haiku-5-5"
MAX_TOKENS = 8192

load_dotenv(BASE_DIR / ".env", encoding="utf-8")


def _get_settings():
    """.env에서 API 키와 모델 이름을 읽는다. 키가 없으면 한글로 안내하고 멈춘다."""
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key or not key.startswith("sk-"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY가 없습니다.\n"
            f"{BASE_DIR / '.env'} 파일을 열어 ANTHROPIC_API_KEY= 뒤에 API 키를 붙여 넣고 저장하세요.\n"
            "(.env 파일이 없으면 .env.example을 복사해서 만드세요.)"
        )
    model = os.getenv("MODEL", "").strip() or DEFAULT_MODEL
    return key, model


def _read_guide(guide_file):
    """지침 폴더 안의 파일을 읽는다. 확장자를 빼고 이름만 써도 된다."""
    path = GUIDE_DIR / guide_file
    if not path.exists() and not path.suffix:
        path = GUIDE_DIR / f"{guide_file}.md"
    if not path.exists():
        raise FileNotFoundError(f"지침 파일을 찾을 수 없습니다: {path}")
    return path.read_text(encoding="utf-8")


def ask(guide_file, user_input):
    """지침 파일을 시스템 프롬프트로, 입력을 사용자 메시지로 보내고 답변 글을 돌려준다."""
    key, model = _get_settings()
    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=_read_guide(guide_file),
        messages=[{"role": "user", "content": user_input}],
    )
    if response.stop_reason == "max_tokens":  # 생각하는 데 토큰을 쓰면 답이 잘리거나 비어 올 수 있다
        raise ValueError(f"AI 답변이 길이 제한({MAX_TOKENS}토큰)에서 잘렸습니다. 다시 실행해 주세요.")
    text = "".join(block.text for block in response.content if block.type == "text")
    if not text.strip():
        raise ValueError("AI가 빈 답변을 보냈습니다. 다시 실행해 주세요.")
    return text


def _extract_json(text):
    """답변에서 JSON만 꺼낸다. ```json 으로 감싸져 있거나 앞뒤에 글이 있어도 처리한다."""
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError(f"답변에서 JSON을 찾지 못했습니다. 답변 원문:\n{text}")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 형식이 올바르지 않습니다: {e}\n답변 원문:\n{text}") from e


def ask_json(guide_file, user_input):
    """ask()의 답변에서 JSON만 꺼내 딕셔너리로 돌려준다."""
    return _extract_json(ask(guide_file, user_input))


if __name__ == "__main__":
    # 확인용: data/접수함의 01번 파일 한 건으로 실행
    sample = next((BASE_DIR / "data" / "접수함").glob("01_*.txt"))
    message = f"파일 이름: {sample.name}\n\n원문:\n{sample.read_text(encoding='utf-8')}"
    print(json.dumps(ask_json("접수정리.md", message), ensure_ascii=False, indent=2))
