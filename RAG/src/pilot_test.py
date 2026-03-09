"""
파일럿 테스트 - ct_cl 기준 층화추출 100건
새 컬럼(smry, genre, asset_prod, series_nm, cast_guest) 채워지는지 검증
"""

import os
import sys
import re
import json
import psycopg2
import psycopg2.pool

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
EPISODE_PATTERN = re.compile(r'\s*((시즌\d+|[A-Za-z]+)\s+)?\d+회\s*$')

SAMPLE_PER_CT_CL = 10  # ct_cl당 샘플 수


def normalize_title(title: str) -> str:
    return EPISODE_PATTERN.sub('', title).strip()


def get_stratified_sample(conn) -> list[dict]:
    """ct_cl별 층화추출"""
    query = """
        SELECT full_asset_id, asset_nm, ct_cl, release_date
        FROM (
            SELECT full_asset_id, asset_nm, ct_cl, release_date,
                   ROW_NUMBER() OVER (PARTITION BY ct_cl ORDER BY RANDOM()) AS rn
            FROM vod
            WHERE (rag_processed IS NULL OR rag_processed = FALSE)
        ) t
        WHERE rn <= %s
        LIMIT 100
    """
    with conn.cursor() as cur:
        cur.execute(query, (SAMPLE_PER_CT_CL,))
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

    result = None
    KMDB_API_KEY = os.getenv("KMDB_API_KEY", "")
    if KMDB_API_KEY and (ct_cl in KOREAN_CT_CL or ct_cl is None):
        kmdb_result = search_kmdb(normalized_nm, year)
        if kmdb_result and (kmdb_result.get("director") or kmdb_result.get("cast_lead")):
            if kids_rating:
                kmdb_result["rating"] = kids_rating
            result = kmdb_result

    if not result:
        content_type = "tv" if ct_cl in KOREAN_CT_CL else "movie"
        tmdb_result = search_tmdb(normalized_nm, year, content_type)
        if tmdb_result and (tmdb_result.get("director") or tmdb_result.get("cast_lead")):
            if kids_rating:
                tmdb_result["rating"] = kids_rating
            result = tmdb_result

    if not result and kids_rating:
        result = {"rating": kids_rating, "source": "rule_based"}

    return result


def run_pilot():
    print("=" * 50)
    print("파일럿 테스트 시작 (ct_cl 층화추출 100건)")
    print("=" * 50)

    conn = psycopg2.connect(**DB_CONFIG)
    vods = get_stratified_sample(conn)

    # ct_cl 분포 출력
    from collections import Counter
    dist = Counter(v["ct_cl"] for v in vods)
    print(f"\n샘플 분포 ({len(vods)}건):")
    for ct, cnt in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {ct}: {cnt}건")
    print()

    results = {"success": 0, "not_found": 0, "by_source": Counter(), "by_ct_cl": Counter()}
    filled = {"director": 0, "cast_lead": 0, "cast_guest": 0, "rating": 0,
              "release_date": 0, "smry": 0, "genre": 0, "asset_prod": 0, "series_nm": 0}

    for i, vod in enumerate(vods, 1):
        asset_nm = vod["asset_nm"]
        ct_cl = vod["ct_cl"]
        result = search_info(asset_nm, ct_cl, vod.get("release_date"))

        if result:
            update_vod(conn, vod["full_asset_id"], result)
            results["success"] += 1
            results["by_source"][result.get("source", "unknown")] += 1
            results["by_ct_cl"][ct_cl] += 1
            for col in filled:
                if result.get(col):
                    filled[col] += 1
            src = result.get("source", "?")
            print(f"[{i:3d}] ✓ {src:10s} | {ct_cl:8s} | {asset_nm[:30]}")
        else:
            mark_not_found(conn, vod["full_asset_id"])
            results["not_found"] += 1
            print(f"[{i:3d}] ✗ not_found  | {ct_cl:8s} | {asset_nm[:30]}")

    conn.close()

    # 결과 요약
    total = len(vods)
    print("\n" + "=" * 50)
    print("파일럿 테스트 결과")
    print("=" * 50)
    print(f"성공: {results['success']}/{total} ({results['success']/total*100:.1f}%)")
    print(f"not_found: {results['not_found']}/{total} ({results['not_found']/total*100:.1f}%)")

    print(f"\n소스별:")
    for src, cnt in results["by_source"].most_common():
        print(f"  {src}: {cnt}건")

    print(f"\n컬럼 채워진 비율:")
    for col, cnt in filled.items():
        bar = "█" * int(cnt / total * 20)
        print(f"  {col:12s}: {cnt:3d}/{total} ({cnt/total*100:5.1f}%) {bar}")

    print("\n전체 파이프라인 진행 여부를 판단하세요!")


if __name__ == "__main__":
    run_pilot()
