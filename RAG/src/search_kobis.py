"""
KOBIS (영화진흥위원회) API 검색 모듈
영화 not_found 결측치 보완용 (일회성)

대상: rag_source = 'not_found' AND ct_cl = '영화'
채우는 항목: director, genre, release_date
※ KOBIS는 smry 미제공
"""

import os
import sys
import time
import re
import psycopg2
import psycopg2.pool
import requests
import threading

from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '../config/.env'))

KOBIS_SEARCH_URL = 'https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie/searchMovieList.json'
KOBIS_DETAIL_URL = 'https://www.kobis.or.kr/kobisopenapi/webservice/rest/movie/searchMovieInfo.json'

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', 5432),
    'dbname': os.getenv('DB_NAME', 'vod_recommendation'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD'),
}
KOBIS_KEY = os.getenv('KOBIS_API_KEY')

EPISODE_PATTERN = re.compile(
    r'\s*((시즌\s*\d+|[Ss]eason\s*\d+|[A-Za-z]+)\s+)?'
    r'\d+\s*(회|화|강|편|부|기)?'
    r'[\.\s]*$',
    re.IGNORECASE
)

_db_pool = None
_print_lock = threading.Lock()
_cache: dict[str, dict | None] = {}
_cache_lock = threading.Lock()


def get_db_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=20, **DB_CONFIG)
    return _db_pool


def safe_print(*args):
    with _print_lock:
        print(*args)


def normalize_title(title: str) -> str:
    result = EPISODE_PATTERN.sub('', title)
    result = re.sub(r'[\.\~\s]+$', '', result)
    result = re.sub(r'\s+', ' ', result)
    return result.strip()


def search_kobis(title: str) -> dict | None:
    """KOBIS API로 영화 검색 → 상세정보 조회 (시리즈 캐싱)"""
    normalized = normalize_title(title)

    with _cache_lock:
        if normalized in _cache:
            return _cache[normalized]

    try:
        time.sleep(0.3)
        # 1단계: 제목으로 검색 → movieCd 획득
        r = requests.get(KOBIS_SEARCH_URL,
                         params={'key': KOBIS_KEY, 'movieNm': normalized, 'itemPerPage': 1},
                         timeout=5)
        movie_list = r.json().get('movieListResult', {}).get('movieList', [])
        if not movie_list:
            with _cache_lock:
                _cache[normalized] = None
            return None

        movie = movie_list[0]
        # 제목 유사도 기본 검증
        if normalized not in movie.get('movieNm', ''):
            with _cache_lock:
                _cache[normalized] = None
            return None

        movie_cd = movie.get('movieCd')

        # 2단계: movieCd로 상세정보 조회
        time.sleep(0.3)
        r2 = requests.get(KOBIS_DETAIL_URL,
                          params={'key': KOBIS_KEY, 'movieCd': movie_cd},
                          timeout=5)
        detail = r2.json().get('movieInfoResult', {}).get('movieInfo', {})
        if not detail:
            with _cache_lock:
                _cache[normalized] = None
            return None

        # 감독
        directors = detail.get('directors', [])
        director = directors[0].get('peopleNm') if directors else None

        # 장르
        genres = detail.get('genres', [])
        genre = genres[0].get('genreNm') if genres else None

        # 개봉일
        open_dt = detail.get('openDt') or None
        release_date = None
        if open_dt and len(open_dt) == 8:
            release_date = f"{open_dt[:4]}-{open_dt[4:6]}-{open_dt[6:8]}"

        # 배우 (주연)
        actors = detail.get('actors', [])
        cast_lead = ', '.join(
            a.get('peopleNm', '') for a in actors[:3] if a.get('cast') in ('주연', '')
        ) or None

        if not (director or genre or release_date):
            with _cache_lock:
                _cache[normalized] = None
            return None

        result = {
            'director': director,
            'genre': genre,
            'release_date': release_date,
            'cast_lead': cast_lead,
        }
        with _cache_lock:
            _cache[normalized] = result
        return result

    except Exception:
        with _cache_lock:
            _cache[normalized] = None
        return None


def get_target_vods(conn) -> list[dict]:
    query = """
        SELECT DISTINCT ON (asset_nm) full_asset_id, asset_nm
        FROM vod
        WHERE rag_source = 'not_found'
          AND ct_cl = '영화'
        ORDER BY asset_nm, full_asset_id
    """
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
        return [{'full_asset_id': r[0], 'asset_nm': r[1]} for r in rows]


def update_vod(conn, full_asset_id: str, data: dict) -> bool:
    fields, values = [], []
    for col in ('director', 'genre', 'release_date', 'cast_lead'):
        if data.get(col):
            fields.append(f'{col} = %s')
            values.append(data[col])
    if not fields:
        return False
    fields.append('rag_source = %s')
    values.append('kobis')
    values.append(full_asset_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE vod SET {', '.join(fields)} WHERE full_asset_id = %s", values)
    conn.commit()
    return True


def process_vod(vod: dict) -> tuple[str, bool]:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        result = search_kobis(vod['asset_nm'])
        if result and update_vod(conn, vod['full_asset_id'], result):
            safe_print(f"  ✓ {vod['asset_nm'][:40]}")
            return vod['asset_nm'], True
        return vod['asset_nm'], False
    except Exception as e:
        safe_print(f"  [오류] {vod['asset_nm']}: {e}")
        try:
            conn.rollback()
        except:
            pass
        return vod['asset_nm'], False
    finally:
        pool.putconn(conn)


def run(max_workers: int = 3):
    print('=' * 50)
    print('KOBIS — 영화 not_found 처리')
    print('=' * 50)

    if not KOBIS_KEY:
        print('KOBIS_API_KEY가 .env에 없습니다.')
        return

    conn = psycopg2.connect(**DB_CONFIG)
    vods = get_target_vods(conn)
    conn.close()

    total = len(vods)
    print(f'대상: {total:,}건\n')
    if total == 0:
        print('처리할 항목 없음.')
        return

    success, fail, done = 0, 0, 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_vod, vod): vod for vod in vods}
        for future in as_completed(futures):
            _, ok = future.result()
            done += 1
            if ok:
                success += 1
            else:
                fail += 1
            if done % 200 == 0:
                print(f'\n[진행] {done:,}/{total:,} ({done/total*100:.1f}%) | 성공:{success:,} 실패:{fail:,}\n')

    print(f'\n완료: 성공 {success:,} / 실패 {fail:,} / 전체 {total:,}')
    print(f'채움률: {success/total*100:.1f}%')


if __name__ == '__main__':
    run(max_workers=3)
