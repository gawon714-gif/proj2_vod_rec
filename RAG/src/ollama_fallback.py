"""
Ollama fallback 모듈
KMDB, TMDB 둘 다 결과 없을 때 로컬 LLM으로 결측치 보완
"""

import requests
import json
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")


def ask_ollama(title: str, ct_cl: str = None) -> dict | None:
    """
    Ollama에게 VOD 정보 질문
    ct_cl: 콘텐츠 유형 (영화, TV드라마, 애니 등)
    Returns: {director, cast_lead, cast_guest, rating, release_date} or None
    """
    prompt = _build_prompt(title, ct_cl)

    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL}/api/generate",
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=60,
        )
        response.raise_for_status()
        raw = response.json().get("response", "")
        return _parse_ollama_response(raw)

    except Exception as e:
        print(f"[Ollama] 오류 ({title}): {e}")
        return None


def _build_prompt(title: str, ct_cl: str = None) -> str:
    content_type = ct_cl if ct_cl else "영상"
    return f""""{title}" ({content_type})의 실제 정보를 JSON으로 출력하세요.
모르는 항목은 반드시 null로 하세요. 추측하지 마세요.

{{
  "director": null,
  "cast_lead": null,
  "cast_guest": null,
  "rating": null,
  "release_date": null
}}

규칙:
- director: 실제 감독 한국어 이름만. 모르면 null
- cast_lead: 주연배우 한국어 이름 배열. 모르면 null
- cast_guest: 조연배우 한국어 이름 배열. 모르면 null
- rating: 전체이용가, 12세이상, 15세이상, 청소년관람불가 중 하나. 모르면 null
- release_date: YYYY-MM-DD 형식. 모르면 null"""


def _parse_ollama_response(raw: str) -> dict | None:
    """Ollama JSON 응답 파싱"""
    try:
        data = json.loads(raw)

        import re

        def clean(val):
            """빈 값, 'null' 문자열 → None으로 정리"""
            if val is None:
                return None
            val = str(val).strip()
            if not val or val.lower() in ("null", "none", "알수없음", "unknown", "모름", "미상", "미정"):
                return None
            # 프롬프트 예시 텍스트가 그대로 들어온 경우 제거
            if "한국어" in val or "이름" in val or "배우" in val:
                return None
            return val

        def clean_date(val):
            """YYYY-MM-DD 형식이 아니면 None"""
            val = clean(val)
            if val and re.match(r'^\d{4}-\d{2}-\d{2}$', str(val)):
                return val
            return None

        VALID_RATINGS = {"전체이용가", "12세이상", "15세이상", "청소년관람불가"}

        director = clean(data.get("director"))
        cast_lead = data.get("cast_lead") or None
        cast_guest = data.get("cast_guest") or None
        raw_rating = clean(data.get("rating"))
        rating = raw_rating if raw_rating in VALID_RATINGS else None
        release_date = clean_date(data.get("release_date"))

        # 모든 값이 None이면 실패로 처리
        if not any([director, cast_lead, rating, release_date]):
            return None

        return {
            "director": director,
            "cast_lead": cast_lead,
            "cast_guest": cast_guest,
            "rating": rating,
            "release_date": release_date,
            "source": "Ollama",
        }

    except json.JSONDecodeError:
        print(f"[Ollama] JSON 파싱 실패: {raw[:100]}")
        return None


if __name__ == "__main__":
    result = ask_ollama("기생충", ct_cl="영화")
    print(result)
