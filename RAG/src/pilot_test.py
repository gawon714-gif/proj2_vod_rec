"""
파일럿 테스트 (드라이런) - ct_cl 기준 층화추출 100건
DB 저장 없이 API 검색 결과만 출력

버전 A: 전체 ct_cl 층화추출
버전 B: 유효 ct_cl만 층화추출 (TMDB/KMDB 커버 높은 장르)
"""

import os
import sys
import re
import argparse
import psycopg2

sys.stdout.reconfigure(encoding="utf-8")
from collections import Counter
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

# 버전 B: TMDB/KMDB 커버리지가 높은 ct_cl만
VALID_CT_CL = {"TV드라마", "영화", "TV애니메이션", "키즈", "TV 연예/오락"}

EPISODE_PATTERN = re.compile(
    r'\s*((시즌\s*\d+|[Ss]eason\s*\d+|[A-Za-z]+)\s+)?'
    r'\d+\s*(회|화|강|편|부)?'
    r'[\.\s]*$',
    re.IGNORECASE
)

SAMPLE_PER_CT_CL = 10  # ct_cl당 샘플 수


def normalize_title(title: str) -> str:
    result = EPISODE_PATTERN.sub('', title)
    result = re.sub(r'[\.\~\s]+$', '', result)
    result = re.sub(r'\s+', ' ', result)
    return result.strip()


def get_stratified_sample(conn, valid_only: bool = False) -> list[dict]:
    """ct_cl별 층화추출 (전체 vod 대상, 드라이런이므로 rag_processed 무관)"""
    if valid_only:
        ct_filter = "AND ct_cl = ANY(%s)"
        params = (SAMPLE_PER_CT_CL, list(VALID_CT_CL))
    else:
        ct_filter = ""
        params = (SAMPLE_PER_CT_CL,)

    query = f"""
        SELECT full_asset_id, asset_nm, ct_cl, release_date
        FROM (
            SELECT full_asset_id, asset_nm, ct_cl, release_date,
                   ROW_NUMBER() OVER (PARTITION BY ct_cl ORDER BY RANDOM()) AS rn
            FROM vod
            WHERE ct_cl IS NOT NULL
            {ct_filter}
        ) t
        WHERE rn <= %s
        LIMIT 100
    """
    # params 순서: valid_only면 ct_cl 리스트 먼저, 그 다음 SAMPLE_PER_CT_CL
    if valid_only:
        final_params = (list(VALID_CT_CL), SAMPLE_PER_CT_CL)
    else:
        final_params = (SAMPLE_PER_CT_CL,)

    with conn.cursor() as cur:
        cur.execute(query, final_params)
        rows = cur.fetchall()
        cols = ["full_asset_id", "asset_nm", "ct_cl", "release_date"]
        return [dict(zip(cols, row)) for row in rows]


def search_info(asset_nm: str, ct_cl: str, release_date=None) -> dict | None:
    """KMDB → TMDB 순으로 검색 (DB 저장 없음)"""
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


def run_pilot(valid_only: bool = False):
    label = "버전 B (유효 ct_cl만)" if valid_only else "버전 A (전체 ct_cl)"
    print("=" * 60)
    print(f"파일럿 테스트 [{label}] - 드라이런 (DB 저장 없음)")
    print("=" * 60)

    conn = psycopg2.connect(**DB_CONFIG)
    vods = get_stratified_sample(conn, valid_only=valid_only)
    conn.close()

    dist = Counter(v["ct_cl"] for v in vods)
    print(f"\n샘플 분포 ({len(vods)}건):")
    for ct, cnt in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"  {ct}: {cnt}건")
    print()

    stats = {"success": 0, "not_found": 0, "by_source": Counter(), "by_ct_cl": Counter()}
    filled = {col: 0 for col in
              ["director", "cast_lead", "cast_guest", "rating",
               "release_date", "smry", "genre", "asset_prod", "series_nm"]}

    for i, vod in enumerate(vods, 1):
        asset_nm = vod["asset_nm"]
        ct_cl = vod["ct_cl"]
        normalized = normalize_title(asset_nm)
        result = search_info(asset_nm, ct_cl, vod.get("release_date"))

        if result:
            stats["success"] += 1
            stats["by_source"][result.get("source", "unknown")] += 1
            stats["by_ct_cl"][ct_cl] += 1
            for col in filled:
                if result.get(col):
                    filled[col] += 1
            src = result.get("source", "?")
            norm_display = f" → '{normalized}'" if normalized != asset_nm else ""
            print(f"[{i:3d}] ✓ {src:10s} | {ct_cl:12s} | {asset_nm[:25]}{norm_display}")
        else:
            stats["not_found"] += 1
            normalized_display = f" → '{normalized}'" if normalized != asset_nm else ""
            print(f"[{i:3d}] ✗ not_found   | {ct_cl:12s} | {asset_nm[:25]}{normalized_display}")

    total = len(vods)
    print("\n" + "=" * 60)
    print(f"결과 요약 [{label}]")
    print("=" * 60)
    print(f"성공:     {stats['success']:3d}/{total} ({stats['success']/total*100:.1f}%)")
    print(f"not_found:{stats['not_found']:3d}/{total} ({stats['not_found']/total*100:.1f}%)")

    print(f"\n소스별:")
    for src, cnt in stats["by_source"].most_common():
        print(f"  {src}: {cnt}건")

    print(f"\nct_cl별 성공:")
    for ct, cnt in stats["by_ct_cl"].most_common():
        print(f"  {ct}: {cnt}건")

    print(f"\n컬럼 채워진 비율:")
    for col, cnt in filled.items():
        bar = "█" * int(cnt / total * 20)
        print(f"  {col:12s}: {cnt:3d}/{total} ({cnt/total*100:5.1f}%) {bar}")

    return stats, filled


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["A", "B", "both"], default="both",
                        help="A=전체ct_cl / B=유효ct_cl만 / both=둘다")
    args = parser.parse_args()

    if args.mode in ("A", "both"):
        stats_a, filled_a = run_pilot(valid_only=False)

    if args.mode == "both":
        print("\n\n")

    if args.mode in ("B", "both"):
        stats_b, filled_b = run_pilot(valid_only=True)

    if args.mode == "both":
        print("\n" + "=" * 60)
        print("비교 요약")
        print("=" * 60)
        total = 100
        print(f"{'':15s} {'버전A(전체)':>12} {'버전B(유효)':>12}")
        print(f"{'성공률':15s} {stats_a['success']/total*100:>11.1f}% {stats_b['success']/total*100:>11.1f}%")
        print(f"{'not_found율':15s} {stats_a['not_found']/total*100:>11.1f}% {stats_b['not_found']/total*100:>11.1f}%")
        print()
        for col in filled_a:
            a = filled_a[col] / total * 100
            b = filled_b[col] / total * 100
            print(f"  {col:12s}: A={a:5.1f}%  B={b:5.1f}%")
