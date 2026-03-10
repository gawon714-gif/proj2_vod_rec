"""
KMDB 재처리 스크립트
- 이전에 KMDB 키 없이 처리된 한국 콘텐츠 (not_found) 를 롤백 후 KMDB 우선으로 재처리
- 대상: rag_source='not_found' AND ct_cl IN ('TV드라마', '스포츠', '키즈', '애니', '시사/교양', '예능')
"""

import os
import sys
import re
import json
import threading
import psycopg2
import psycopg2.pool

from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding="utf-8")
from dotenv import load_dotenv
from search_kmdb import search_kmdb
from search_tmdb import search_tmdb

load_dotenv(os.path.join(os.path.dirname(__file__), "../config/.env"))

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", 5432),
    "dbname": os.getenv("DB_NAME", "vod_recommendation"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
}

KOREAN_CT_CL = {"TV드라마", "예능", "키즈", "애니", "시사/교양", "스포츠"}
KIDS_CT_CL = {"키즈"}
KIDS_DEFAULT_RATING = "전체이용가"
EPISODE_PATTERN = re.compile(
    r'\s*((시즌\s*\d+|[Ss]eason\s*\d+|[A-Za-z]+)\s+)?'
    r'\d+\s*(회|화|강|편|부)?'
    r'[\.\s]*$',
    re.IGNORECASE
)

_series_cache: dict[tuple, dict | None] = {}
_cache_lock = threading.Lock()
_print_lock = threading.Lock()
_db_pool = None


def get_db_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=40, **DB_CONFIG)
    return _db_pool


def safe_print(*args):
    with _print_lock:
        print(*args)


def normalize_title(title: str) -> str:
    result = EPISODE_PATTERN.sub('', title)
    result = re.sub(r'[\.\~\s]+$', '', result)
    result = re.sub(r'\s+', ' ', result)
    return result.strip()


def rollback_targets(conn) -> int:
    """not_found 한국 콘텐츠를 미처리 상태로 롤백"""
    query = """
        UPDATE vod
        SET rag_processed = FALSE,
            rag_source = NULL,
            rag_processed_at = NULL
        WHERE rag_source = 'not_found'
          AND ct_cl = ANY(%s)
    """
    with conn.cursor() as cur:
        cur.execute(query, (list(KOREAN_CT_CL),))
        count = cur.rowcount
    conn.commit()
    return count


def get_targets(conn, limit: int = 200000) -> list[dict]:
    """롤백된 한국 콘텐츠 목록 조회"""
    query = """
        SELECT full_asset_id, asset_nm, ct_cl, release_date
        FROM vod
        WHERE (rag_processed IS NULL OR rag_processed = FALSE)
          AND ct_cl = ANY(%s)
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(query, (list(KOREAN_CT_CL), limit))
        rows = cur.fetchall()
        cols = ["full_asset_id", "asset_nm", "ct_cl", "release_date"]
        return [dict(zip(cols, row)) for row in rows]


def update_vod(conn, full_asset_id: str, data: dict):
    fields, values = [], []
    for col in ("director", "rating", "release_date", "smry", "genre", "asset_prod", "series_nm"):
        if data.get(col):
            fields.append(f"{col} = %s")
            values.append(data[col])
    for col in ("cast_lead", "cast_guest"):
        if data.get(col):
            fields.append(f"{col} = %s")
            values.append(json.dumps(data[col], ensure_ascii=False))
    fields += ["rag_processed = TRUE", "rag_source = %s", "rag_processed_at = NOW()"]
    values += [data.get("source", "unknown"), full_asset_id]
    with conn.cursor() as cur:
        cur.execute(f"UPDATE vod SET {', '.join(fields)} WHERE full_asset_id = %s", values)
    conn.commit()


def mark_not_found(conn, full_asset_id: str):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE vod SET rag_processed = TRUE, rag_source = 'not_found', rag_processed_at = NOW()
            WHERE full_asset_id = %s
        """, (full_asset_id,))
    conn.commit()


def search_info(asset_nm: str, ct_cl: str, release_date=None) -> dict | None:
    year = str(release_date.year) if release_date else None
    normalized_nm = normalize_title(asset_nm)
    kids_rating = KIDS_DEFAULT_RATING if ct_cl in KIDS_CT_CL else None
    cache_key = (normalized_nm, ct_cl)

    with _cache_lock:
        if cache_key in _series_cache:
            return _series_cache[cache_key]

    result = None

    # 1. KMDB 우선
    KMDB_API_KEY = os.getenv("KMDB_API_KEY", "")
    if KMDB_API_KEY:
        kmdb_result = search_kmdb(normalized_nm, year)
        if kmdb_result and (kmdb_result.get("director") or kmdb_result.get("cast_lead")):
            if kids_rating:
                kmdb_result["rating"] = kids_rating
            safe_print(f"  [KMDB] '{asset_nm}' 찾음")
            result = kmdb_result

    # 2. TMDB 폴백
    if not result:
        tmdb_result = search_tmdb(normalized_nm, year, "tv")
        if tmdb_result and (tmdb_result.get("director") or tmdb_result.get("cast_lead")):
            if kids_rating:
                tmdb_result["rating"] = kids_rating
            safe_print(f"  [TMDB] '{asset_nm}' 찾음")
            result = tmdb_result

    # 3. 키즈 fallback
    if not result and kids_rating:
        safe_print(f"  [규칙] '{asset_nm}' → 전체이용가")
        result = {"rating": kids_rating, "source": "rule_based"}

    with _cache_lock:
        _series_cache[cache_key] = result

    return result


def process_vod(vod: dict) -> tuple[str, bool]:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        result = search_info(vod["asset_nm"], vod["ct_cl"], vod.get("release_date"))
        if result:
            update_vod(conn, vod["full_asset_id"], result)
            return vod["asset_nm"], True
        else:
            mark_not_found(conn, vod["full_asset_id"])
            return vod["asset_nm"], False
    except Exception as e:
        safe_print(f"  [오류] '{vod['asset_nm']}': {e}")
        try:
            conn.rollback()
        except:
            pass
        return vod["asset_nm"], False
    finally:
        pool.putconn(conn)


def run_retry(max_workers: int = 10):
    print("=== KMDB 재처리 시작 ===")

    conn = psycopg2.connect(**DB_CONFIG)

    # 롤백
    rolled_back = rollback_targets(conn)
    print(f"롤백 완료: {rolled_back:,}개 → 미처리 상태로 변경")

    vods = get_targets(conn, limit=200000)
    conn.close()

    total = len(vods)
    print(f"재처리 대상: {total:,}개\n")

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
            if done % 1000 == 0:
                pct = done / total * 100
                print(f"\n[진행] {done:,}/{total:,} ({pct:.1f}%) | 성공:{success:,} 실패:{fail:,}\n")

    print(f"\n완료: 성공 {success:,}개 / 실패 {fail:,}개")


if __name__ == "__main__":
    run_retry(max_workers=10)
