"""
TVMaze API 검색 모듈
TV 연예/오락, TV드라마, TV 시사/교양 not_found 결측치 보완용 (일회성)

대상: rag_source = 'not_found' AND ct_cl IN ('TV 연예/오락', 'TV드라마', 'TV 시사/교양')
채우는 항목: smry, release_date
"""

import os
import sys
import time
import re
import psycopg2
import psycopg2.pool
import requests
import threading
import html

from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '../config/.env'))

TVMAZE_URL = 'https://api.tvmaze.com/singlesearch/shows'

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


def search_tvmaze(title: str) -> dict | None:
    """TVMaze API로 TV 프로그램 검색 (시리즈 캐싱)"""
    normalized = normalize_title(title)

    with _cache_lock:
        if normalized in _cache:
            return _cache[normalized]

    try:
        time.sleep(0.3)
        r = requests.get(TVMAZE_URL, params={'q': normalized}, timeout=5)
        if r.status_code == 429:
            time.sleep(3)
            r = requests.get(TVMAZE_URL, params={'q': normalized}, timeout=5)
        if r.status_code != 200:
            with _cache_lock:
                _cache[normalized] = None
            return None

        data = r.json()

        # smry (HTML 태그 제거)
        smry_raw = data.get('summary') or None
        smry = None
        if smry_raw:
            smry = re.sub(r'<[^>]+>', '', smry_raw)
            smry = html.unescape(smry).strip()
            if len(smry) < 10:
                smry = None

        # release_date
        release_date = data.get('premiered') or None

        # genre
        genres = data.get('genres', [])
        genre = genres[0] if genres else None

        if not (smry or release_date):
            with _cache_lock:
                _cache[normalized] = None
            return None

        result = {
            'smry': smry,
            'genre': genre,
            'release_date': release_date,
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
          AND ct_cl IN ('TV 연예/오락', 'TV드라마', 'TV 시사/교양', '다큐', '공연/음악')
        ORDER BY asset_nm, full_asset_id
    """
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
        return [{'full_asset_id': r[0], 'asset_nm': r[1]} for r in rows]


def update_vod(conn, full_asset_id: str, data: dict) -> bool:
    fields, values = [], []
    for col in ('smry', 'genre', 'release_date'):
        if data.get(col):
            fields.append(f'{col} = %s')
            values.append(data[col])
    if not fields:
        return False
    fields.append('rag_source = %s')
    values.append('tvmaze')
    values.append(full_asset_id)
    with conn.cursor() as cur:
        cur.execute(f"UPDATE vod SET {', '.join(fields)} WHERE full_asset_id = %s", values)
    conn.commit()
    return True


def process_vod(vod: dict) -> tuple[str, bool]:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        result = search_tvmaze(vod['asset_nm'])
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


def run(max_workers: int = 5):
    print('=' * 50)
    print('TVMaze — TV 프로그램 not_found 처리')
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
    run(max_workers=5)
