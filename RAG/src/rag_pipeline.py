"""
RAG 메인 파이프라인 (병렬 처리 버전)
DB에서 결측치 있는 VOD를 가져와서 KMDB → TMDB 순으로 검색 후 DB에 저장
Ollama 제거 - TMDB/KMDB 위주로 빠르게 처리
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

# DB 연결 설정
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", 5432),
    "dbname": os.getenv("DB_NAME", "vod_recommendation"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
}

# 한국 콘텐츠 유형 (KMDB 우선 검색)
KOREAN_CT_CL = {"TV드라마", "예능", "키즈", "애니", "시사/교양", "스포츠"}

# 키즈 rating 규칙 기반
KIDS_CT_CL = {"키즈"}
KIDS_DEFAULT_RATING = "전체이용가"

# 회차/시즌 정보 제거 정규식 (회/화/강/편/부 + 끝 마침표 처리)
EPISODE_PATTERN = re.compile(
    r'\s*((시즌\s*\d+|[Ss]eason\s*\d+|[A-Za-z]+)\s+)?'
    r'\d+\s*(회|화|강|편|부)?'
    r'[\.\s]*$',
    re.IGNORECASE
)

# 시리즈 캐시 (thread-safe)
_series_cache: dict[tuple, dict | None] = {}
_cache_lock = threading.Lock()

# 출력 락 (병렬 출력 섞임 방지)
_print_lock = threading.Lock()

# DB 연결 풀 (워커별 독립 연결)
_db_pool = None


def get_db_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=40,
            **DB_CONFIG
        )
    return _db_pool


def safe_print(*args):
    with _print_lock:
        print(*args)


def normalize_title(title: str) -> str:
    """에피소드/회차 정보 제거해서 시리즈명만 추출"""
    result = EPISODE_PATTERN.sub('', title)
    result = re.sub(r'[\.\~\s]+$', '', result)   # 끝 마침표/특수문자 제거
    result = re.sub(r'\s+', ' ', result)          # 연속 공백 정리
    return result.strip()


def get_vods_with_missing(conn, limit: int = 200000) -> list[dict]:
    """결측치가 있는 VOD 목록 조회 (RAG 미처리 것만)"""
    query = """
        SELECT full_asset_id, asset_nm, ct_cl, release_date
        FROM vod
        WHERE (director IS NULL
           OR cast_lead IS NULL
           OR cast_guest IS NULL
           OR rating IS NULL
           OR release_date IS NULL
           OR series_nm IS NULL
           OR smry IS NULL
           OR genre IS NULL
           OR asset_prod IS NULL)
          AND (rag_processed IS NULL OR rag_processed = FALSE)
        LIMIT %s
    """
    with conn.cursor() as cur:
        cur.execute(query, (limit,))
        rows = cur.fetchall()
        cols = ["full_asset_id", "asset_nm", "ct_cl", "release_date"]
        return [dict(zip(cols, row)) for row in rows]


def update_vod(conn, full_asset_id: str, data: dict):
    """VOD 결측치 업데이트"""
    fields = []
    values = []

    if data.get("director"):
        fields.append("director = %s")
        values.append(data["director"])
    if data.get("cast_lead"):
        fields.append("cast_lead = %s")
        values.append(json.dumps(data["cast_lead"], ensure_ascii=False))
    if data.get("cast_guest"):
        fields.append("cast_guest = %s")
        values.append(json.dumps(data["cast_guest"], ensure_ascii=False))
    if data.get("rating"):
        fields.append("rating = %s")
        values.append(data["rating"])
    if data.get("release_date"):
        fields.append("release_date = %s")
        values.append(data["release_date"])
    if data.get("smry"):
        fields.append("smry = %s")
        values.append(data["smry"])
    if data.get("genre"):
        fields.append("genre = %s")
        values.append(data["genre"])
    if data.get("asset_prod"):
        fields.append("asset_prod = %s")
        values.append(data["asset_prod"])
    if data.get("series_nm"):
        fields.append("series_nm = %s")
        values.append(data["series_nm"])

    fields.append("rag_processed = TRUE")
    fields.append("rag_source = %s")
    values.append(data.get("source", "unknown"))
    fields.append("rag_processed_at = NOW()")

    values.append(full_asset_id)
    query = f"UPDATE vod SET {', '.join(fields)} WHERE full_asset_id = %s"

    with conn.cursor() as cur:
        cur.execute(query, values)
    conn.commit()


def mark_rag_failed(conn, full_asset_id: str):
    """RAG 검색 실패 시 rag_processed 마킹 (무한반복 방지)"""
    query = """
        UPDATE vod SET
            rag_processed = TRUE,
            rag_source = 'not_found',
            rag_processed_at = NOW()
        WHERE full_asset_id = %s
    """
    with conn.cursor() as cur:
        cur.execute(query, (full_asset_id,))
    conn.commit()


def search_info(asset_nm: str, ct_cl: str, release_date=None) -> dict | None:
    """KMDB → TMDB 순으로 정보 검색 (Ollama 제거)"""
    year = str(release_date.year) if release_date else None

    normalized_nm = normalize_title(asset_nm)
    kids_rating = KIDS_DEFAULT_RATING if ct_cl in KIDS_CT_CL else None
    cache_key = (normalized_nm, ct_cl)

    # 캐시 확인
    with _cache_lock:
        if cache_key in _series_cache:
            return _series_cache[cache_key]

    result = None

    # 1. KMDB (한국 콘텐츠, 키가 있을 때만)
    KMDB_API_KEY = os.getenv("KMDB_API_KEY", "")
    if KMDB_API_KEY and (ct_cl in KOREAN_CT_CL or ct_cl is None):
        kmdb_result = search_kmdb(normalized_nm, year)
        if kmdb_result and (kmdb_result.get("director") or kmdb_result.get("cast_lead")):
            if kids_rating:
                kmdb_result["rating"] = kids_rating
            safe_print(f"  [KMDB] '{asset_nm}' 찾음")
            result = kmdb_result

    # 2. TMDB
    if not result:
        content_type = "tv" if ct_cl in KOREAN_CT_CL else "movie"
        tmdb_result = search_tmdb(normalized_nm, year, content_type)
        if tmdb_result and (tmdb_result.get("director") or tmdb_result.get("cast_lead")):
            if kids_rating:
                tmdb_result["rating"] = kids_rating
            safe_print(f"  [TMDB] '{asset_nm}' 찾음")
            result = tmdb_result

    # 3. 키즈 fallback - rating만 저장
    if not result and kids_rating:
        safe_print(f"  [규칙] '{asset_nm}' → 전체이용가")
        result = {"rating": kids_rating, "source": "rule_based"}

    # 캐시 저장
    with _cache_lock:
        _series_cache[cache_key] = result

    return result


def process_vod(vod: dict) -> tuple[str, bool]:
    """단일 VOD 처리 (워커 함수)"""
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        asset_nm = vod["asset_nm"]
        ct_cl = vod["ct_cl"]

        result = search_info(asset_nm, ct_cl, vod.get("release_date"))

        if result:
            update_vod(conn, vod["full_asset_id"], result)
            return asset_nm, True
        else:
            mark_rag_failed(conn, vod["full_asset_id"])
            return asset_nm, False

    except Exception as e:
        safe_print(f"  [오류] '{vod['asset_nm']}': {e}")
        try:
            conn.rollback()
        except:
            pass
        return vod["asset_nm"], False
    finally:
        pool.putconn(conn)


def run_pipeline(max_workers: int = 10):
    """메인 파이프라인 실행 (병렬 처리)"""
    print(f"RAG 파이프라인 시작 (병렬 {max_workers}개 워커)")

    # VOD 목록 조회용 단일 연결
    conn = psycopg2.connect(**DB_CONFIG)
    vods = get_vods_with_missing(conn, limit=200000)
    conn.close()

    total = len(vods)
    print(f"결측치 VOD {total:,}개 처리 시작\n")

    success = 0
    fail = 0
    done = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_vod, vod): vod for vod in vods}

        for future in as_completed(futures):
            asset_nm, ok = future.result()
            done += 1
            if ok:
                success += 1
            else:
                fail += 1

            # 1000개마다 진행상황 출력
            if done % 1000 == 0:
                pct = done / total * 100
                print(f"\n[진행] {done:,}/{total:,} ({pct:.1f}%) | 성공:{success:,} 실패:{fail:,}\n")

    print(f"\n완료: 성공 {success:,}개 / 실패 {fail:,}개")


if __name__ == "__main__":
    run_pipeline(max_workers=10)
