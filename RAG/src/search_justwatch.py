"""
JustWatch GraphQL API 검색 모듈
smry, director 결측치 보완용 (일회성)

우선순위:
1. smry NULL + rag_processed=TRUE + rag_source != 'not_found' (184건)
2. director NULL + rag_processed=TRUE + rag_source != 'not_found' (7,271건)
3. not_found (72,120건)
"""

import os
import sys
import json
import time
import psycopg2
import psycopg2.pool
import httpx
import threading

from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
from simplejustwatchapi import query as jw_query

load_dotenv(os.path.join(os.path.dirname(__file__), '../config/.env'))

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', 5432),
    'dbname': os.getenv('DB_NAME', 'vod_recommendation'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD'),
}

_SEARCH_QUERY = jw_query._GRAPHQL_SEARCH_QUERY + jw_query._GRAPHQL_DETAILS_FRAGMENT + jw_query._GRAPHQL_OFFER_FRAGMENT
_db_pool = None
_print_lock = threading.Lock()


def get_db_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=40, **DB_CONFIG)
    return _db_pool


def safe_print(*args):
    with _print_lock:
        print(*args)


def search_justwatch(title: str) -> dict | None:
    """JustWatch GraphQL로 smry, rating 검색 (한국어 우선, 실패 시 영어)"""
    time.sleep(0.5)  # API 차단 방지
    for language, country in [('ko', 'KR'), ('en', 'US')]:
        try:
            payload = {
                'query': _SEARCH_QUERY,
                'variables': {
                    'searchTitlesFilter': {'searchQuery': title},
                    'language': language,
                    'country': country,
                    'first': 1,
                    'formatPoster': 'JPG',
                    'formatOfferIcon': 'PNG',
                    'profile': 'S276',
                    'backdropProfile': 'S1920',
                    'filter': {}
                }
            }
            r = httpx.post('https://apis.justwatch.com/graphql', json=payload, timeout=5)
            data = r.json()
            edges = data.get('data', {}).get('popularTitles', {}).get('edges', [])
            if not edges:
                continue
            content = edges[0]['node']['content']
            smry = content.get('shortDescription') or None
            rating = content.get('ageCertification') or None
            if smry or rating:
                return {'smry': smry, 'rating': rating, 'source': 'justwatch'}
        except Exception:
            continue
    return None


def get_target_vods(conn, priority: int) -> list[dict]:
    """우선순위별 대상 VOD 조회"""
    if priority == 1:
        # smry NULL + 처리됐지만 못 채운 것
        query = """
            SELECT full_asset_id, asset_nm
            FROM vod
            WHERE smry IS NULL
              AND rag_processed = TRUE
              AND rag_source != 'not_found'
        """
    elif priority == 2:
        # director NULL + 처리됐지만 못 채운 것 (JustWatch는 director 미제공이므로 smry 보완)
        query = """
            SELECT full_asset_id, asset_nm
            FROM vod
            WHERE director IS NULL
              AND rag_processed = TRUE
              AND rag_source != 'not_found'
        """
    else:
        # not_found 전체
        query = """
            SELECT full_asset_id, asset_nm
            FROM vod
            WHERE rag_source = 'not_found'
        """
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
        return [{'full_asset_id': r[0], 'asset_nm': r[1]} for r in rows]


def update_vod(conn, full_asset_id: str, data: dict):
    """결측치 업데이트"""
    fields = []
    values = []
    if data.get('smry'):
        fields.append('smry = %s')
        values.append(data['smry'])
    if data.get('rating'):
        fields.append('rating = %s')
        values.append(data['rating'])
    if not fields:
        return
    fields.append('rag_source = %s')
    values.append('justwatch')
    values.append(full_asset_id)
    query = f"UPDATE vod SET {', '.join(fields)} WHERE full_asset_id = %s"
    with conn.cursor() as cur:
        cur.execute(query, values)
    conn.commit()


def process_vod(vod: dict) -> tuple[str, bool]:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        result = search_justwatch(vod['asset_nm'])
        if result and (result.get('smry') or result.get('rating')):
            update_vod(conn, vod['full_asset_id'], result)
            safe_print(f"  ✓ {vod['asset_nm'][:30]}")
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


def run(priority: int, max_workers: int = 10):
    label = {1: 'smry NULL (처리완료분)', 2: 'director NULL (처리완료분)', 3: 'not_found'}
    print(f"\n{'='*50}")
    print(f"[{priority}순위] {label[priority]}")
    print(f"{'='*50}")

    conn = psycopg2.connect(**DB_CONFIG)
    vods = get_target_vods(conn, priority)
    conn.close()

    total = len(vods)
    print(f"대상: {total:,}건\n")
    if total == 0:
        print("처리할 항목 없음.")
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
            if done % 500 == 0:
                print(f"\n[진행] {done:,}/{total:,} ({done/total*100:.1f}%) | 성공:{success:,} 실패:{fail:,}\n")

    print(f"\n완료: 성공 {success:,} / 실패 {fail:,} / 전체 {total:,}")
    print(f"채움률: {success/total*100:.1f}%")


if __name__ == '__main__':
    for priority in [1, 2, 3]:
        run(priority, max_workers=10)
