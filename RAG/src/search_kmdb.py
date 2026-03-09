"""
KMDB API 검색 모듈
한국 콘텐츠의 결측치(director, cast_lead, cast_guest, rating, release_date)를 채움
"""

import requests
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

KMDB_API_KEY = os.getenv("KMDB_API_KEY")


def search_kmdb(title: str, year: str = None) -> dict | None:
    """
    KMDB에서 영화/드라마 정보 검색
    Returns: {director, cast_lead, cast_guest, rating, release_date} or None
    """
    params = {
        "title": title,
        "listCount": 5,
        "detail": "Y",
    }
    if year:
        params["releaseDts"] = year

    try:
        # KMDB 자체 API (koreafilm.or.kr) - 별도 키 필요
        params["ServiceKey"] = KMDB_API_KEY
        url = "http://api.koreafilm.or.kr/openapi-data2/wisenut/search_api/search_json2.jsp"
        response = requests.get(url, params=params, timeout=3)
        response.raise_for_status()
        data = response.json()

        result = data.get("Data", [{}])
        if not result or not result[0].get("Result"):
            return None

        item = result[0]["Result"][0]
        return _parse_kmdb_result(item)

    except Exception as e:
        print(f"[KMDB] 검색 오류 ({title}): {e}")
        return None


def _parse_kmdb_result(item: dict) -> dict:
    """KMDB 응답에서 필요한 필드 추출"""
    # 감독
    directors = item.get("directors", {}).get("director", [])
    director = directors[0].get("directorNm", None) if directors else None

    # 주연/조연 배우
    actors = item.get("actors", {}).get("actor", [])
    cast_lead = []
    cast_guest = []
    for actor in actors:
        name = actor.get("actorNm", "")
        role_type = actor.get("actorTypeNm", "")
        if not name:
            continue
        if role_type in ("주연", ""):
            cast_lead.append(name)
        else:
            cast_guest.append(name)

    # 관람등급
    rating = item.get("rating") or None

    # 개봉일 YYYYMMDD -> YYYY-MM-DD
    release_date = item.get("repRlsDate", None)
    if release_date and len(release_date) == 8:
        release_date = f"{release_date[:4]}-{release_date[4:6]}-{release_date[6:8]}"
    else:
        release_date = None

    # 줄거리 (한국어 우선)
    smry = None
    plots = item.get("plots", {}).get("plot", [])
    for p in plots:
        if p.get("plotLang") == "한국어":
            smry = p.get("plotText") or None
            break
    if not smry and plots:
        smry = plots[0].get("plotText") or None

    # 장르
    genre = item.get("genre") or None
    if genre:
        genre = genre.split(",")[0].strip()  # 첫 번째 장르만

    # 제작사
    asset_prod = item.get("prodCompany") or None

    # 시리즈명 (KMDB titleNm)
    series_nm = item.get("titleNm") or None

    return {
        "director": director,
        "cast_lead": cast_lead if cast_lead else None,
        "cast_guest": cast_guest if cast_guest else None,
        "rating": rating,
        "release_date": release_date,
        "smry": smry,
        "genre": genre,
        "asset_prod": asset_prod,
        "series_nm": series_nm,
        "source": "KMDB",
    }


if __name__ == "__main__":
    result = search_kmdb("기생충")
    print(result)
