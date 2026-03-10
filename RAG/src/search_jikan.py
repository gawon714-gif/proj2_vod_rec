"""
Jikan API (MyAnimeList) 검색 모듈
TV애니메이션 not_found 결측치 보완용 (일회성)

대상: rag_source = 'not_found' AND ct_cl = 'TV애니메이션'
채우는 항목: smry, director, cast_lead, genre, release_date
"""

import os
import sys
import time
import psycopg2
import psycopg2.pool
import requests
import re
import threading

from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '../config/.env'))

JIKAN_BASE_URL = 'https://api.jikan.moe/v4'

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', 5432),
    'dbname': os.getenv('DB_NAME', 'vod_recommendation'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD'),
}

EPISODE_PATTERN = re.compile(
    r'\s*((시즌\s*\d+|[Ss]eason\s*\d+|[A-Za-z]+)\s+)?'
    r'\d+\s*(회|화|강|편|부|기)?'
    r'[\.\s]*$',
    re.IGNORECASE
)

_db_pool = None
_print_lock = threading.Lock()
_series_cache: dict[str, dict | None] = {}
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


def search_jikan(title: str) -> dict | None:
    """Jikan API로 애니메이션 검색 (시리즈 캐싱으로 중복 호출 방지)"""
    normalized = normalize_title(title)

    # 캐시 확인
    with _cache_lock:
        if normalized in _series_cache:
            return _series_cache[normalized]

    try:
        time.sleep(0.4)  # Jikan rate limit: 3req/sec
        url = f'{JIKAN_BASE_URL}/anime'
        params = {'q': normalized, 'limit': 1}
        r = requests.get(url, params=params, timeout=5)
        if r.status_code == 429:
            time.sleep(2)
            r = requests.get(url, params=params, timeout=5)
        r.raise_for_status()
        data = r.json().get('data', [])

        if not data:
            with _cache_lock:
                _series_cache[normalized] = None
            return None

        item = data[0]

        # 줄거리 (영어 그대로 저장 — 나중에 일괄 번역)
        smry = item.get('synopsis') or None
        if smry:
            smry = smry.replace('\n', ' ').replace('[Written by MAL Rewrite]', '').strip()
            if len(smry) < 10:
                smry = None

        # 장르
        genres = item.get('genres', [])
        genre = genres[0]['name'] if genres else None

        # 개봉일
        aired = item.get('aired', {}).get('from')
        release_date = aired[:10] if aired else None

        # 제작사
        studios = item.get('studios', [])
        asset_prod = studios[0]['name'] if studios else None

        if not (smry or genre or release_date):
            with _cache_lock:
                _series_cache[normalized] = None
            return None

        result = {
            'smry': smry,
            'genre': genre,
            'release_date': release_date,
            'asset_prod': asset_prod,
            'source': 'jikan'
        }
        with _cache_lock:
            _series_cache[normalized] = result
        return result
    except Exception:
        with _cache_lock:
            _series_cache[normalized] = None
        return None


def get_target_vods(conn) -> list[dict]:
    """TV애니메이션 not_found 조회"""
    query = """
        SELECT DISTINCT ON (asset_nm) full_asset_id, asset_nm
        FROM vod
        WHERE rag_source = 'not_found'
          AND ct_cl = 'TV애니메이션'
        ORDER BY asset_nm, full_asset_id
    """
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
        return [{'full_asset_id': r[0], 'asset_nm': r[1]} for r in rows]


def update_vod(conn, full_asset_id: str, data: dict):
    fields = []
    values = []
    if data.get('smry'):
        fields.append('smry = %s')
        values.append(data['smry'])
    if data.get('genre'):
        fields.append('genre = %s')
        values.append(data['genre'])
    if data.get('release_date'):
        fields.append('release_date = %s')
        values.append(data['release_date'])
    if data.get('asset_prod'):
        fields.append('asset_prod = %s')
        values.append(data['asset_prod'])
    if not fields:
        return False
    fields.append('rag_source = %s')
    values.append('jikan')
    values.append(full_asset_id)
    query = f"UPDATE vod SET {', '.join(fields)} WHERE full_asset_id = %s"
    with conn.cursor() as cur:
        cur.execute(query, values)
    conn.commit()
    return True


def process_vod(vod: dict) -> tuple[str, bool]:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        result = search_jikan(vod['asset_nm'])
        if result:
            updated = update_vod(conn, vod['full_asset_id'], result)
            if updated:
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
    print('Jikan API — TV애니메이션 not_found 처리')
    print('=' * 50)

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
