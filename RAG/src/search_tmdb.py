"""
TMDB API 검색 모듈
해외 콘텐츠의 결측치(director, cast_lead, cast_guest, rating, release_date)를 채움
language=ko-KR 파라미터로 처음부터 한국어로 반환받음
"""

import requests
import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

TMDB_API_KEY = os.getenv("TMDB_API_KEY")
TMDB_BASE_URL = "https://api.themoviedb.org/3"


def search_tmdb(title: str, year: str = None, content_type: str = "movie") -> dict | None:
    """
    TMDB에서 영화/TV 정보 검색
    content_type: 'movie' 또는 'tv'
    Returns: {director, cast_lead, cast_guest, rating, release_date} or None
    """
    # 1단계: 제목으로 검색
    search_endpoint = f"{TMDB_BASE_URL}/search/{content_type}"
    params = {
        "api_key": TMDB_API_KEY,
        "query": title,
        "language": "ko-KR",
    }
    if year:
        params["year"] = year

    try:
        response = requests.get(search_endpoint, params=params, timeout=3)
        response.raise_for_status()
        results = response.json().get("results", [])

        if not results:
            return None

        # 2단계: 첫 번째 결과의 상세 정보 가져오기
        item_id = results[0]["id"]
        return _get_tmdb_details(item_id, content_type)

    except Exception as e:
        print(f"[TMDB] 검색 오류 ({title}): {e}")
        return None


def _get_tmdb_details(item_id: int, content_type: str) -> dict | None:
    """TMDB ID로 상세 정보 + 크레딧 조회"""
    try:
        # 상세 정보
        detail_url = f"{TMDB_BASE_URL}/{content_type}/{item_id}"
        credit_url = f"{TMDB_BASE_URL}/{content_type}/{item_id}/credits"
        params = {"api_key": TMDB_API_KEY, "language": "ko-KR"}
        # 영화는 release_dates(등급)를 한 번에 가져옴
        if content_type == "movie":
            params["append_to_response"] = "release_dates"

        detail_resp = requests.get(detail_url, params=params, timeout=3)
        credit_resp = requests.get(credit_url, params=params, timeout=3)

        detail_resp.raise_for_status()
        credit_resp.raise_for_status()

        detail = detail_resp.json()
        credits = credit_resp.json()

        return _parse_tmdb_result(detail, credits, content_type)

    except Exception as e:
        print(f"[TMDB] 상세 조회 오류 (id={item_id}): {e}")
        return None


def _parse_tmdb_result(detail: dict, credits: dict, content_type: str) -> dict:
    """TMDB 응답에서 필요한 필드 추출"""
    # 감독 (영화: crew의 Director / TV: created_by 또는 crew의 Director)
    crew = credits.get("crew", [])
    directors = [c["name"] for c in crew if c.get("job") == "Director"]
    if not directors and content_type == "tv":
        created_by = detail.get("created_by", [])
        directors = [c["name"] for c in created_by]
    director = directors[0] if directors else None

    # 주연 배우 (상위 5명)
    cast = credits.get("cast", [])
    cast_lead = [a["name"] for a in cast[:5]] if cast else None
    cast_guest = [a["name"] for a in cast[5:15]] if len(cast) > 5 else None

    # 관람등급 (append_to_response=release_dates 로 가져온 데이터)
    rating = None
    release_dates = detail.get("release_dates", {}).get("results", [])
    for r in release_dates:
        if r.get("iso_3166_1") == "KR":
            certs = r.get("release_dates", [])
            if certs:
                rating = certs[0].get("certification") or None
            break

    # 개봉일
    if content_type == "movie":
        release_date = detail.get("release_date") or None
    else:
        release_date = detail.get("first_air_date") or None

    # 줄거리
    smry = detail.get("overview") or None

    # 장르 (첫 번째)
    genres = detail.get("genres", [])
    genre = genres[0]["name"] if genres else None

    # 제작사 (첫 번째)
    prod_companies = detail.get("production_companies", [])
    asset_prod = prod_companies[0]["name"] if prod_companies else None

    # 시리즈명 (TV만)
    series_nm = detail.get("name") or None if content_type == "tv" else None

    return {
        "director": director,
        "cast_lead": cast_lead,
        "cast_guest": cast_guest if cast_guest else None,
        "rating": rating,
        "release_date": release_date,
        "smry": smry,
        "genre": genre,
        "asset_prod": asset_prod,
        "series_nm": series_nm,
        "source": "TMDB",
    }


if __name__ == "__main__":
    result = search_tmdb("기생충", content_type="movie")
    print(result)
