"""
영어 smry → 한국어 번역 모듈 (일회성)

대상: rag_source = 'jikan' AND smry IS NOT NULL (영어로 저장된 것)
방식: Google Translate (무료, deep-translator)
배치: 100건씩 묶어서 처리
"""

import os
import sys
import time
import re
import psycopg2
import psycopg2.pool
import threading

from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv
from deep_translator import GoogleTranslator

load_dotenv(os.path.join(os.path.dirname(__file__), '../config/.env'))

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', 5432),
    'dbname': os.getenv('DB_NAME', 'vod_recommendation'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD'),
}

HAS_KOREAN = re.compile(r'[가-힣]')

_db_pool = None
_print_lock = threading.Lock()


def get_db_pool():
    global _db_pool
    if _db_pool is None:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=20, **DB_CONFIG)
    return _db_pool


def safe_print(*args):
    with _print_lock:
        print(*args)


def is_english(text: str) -> bool:
    """한국어 비율이 낮으면 영어로 판단"""
    if not text:
        return False
    return not HAS_KOREAN.search(text)


def translate_to_ko(text: str) -> str | None:
    """영어 → 한국어 번역 (5000자 초과 시 잘라서 처리)"""
    try:
        # Google Translate 무료 한도: 5000자
        if len(text) > 4900:
            text = text[:4900]
        result = GoogleTranslator(source='en', target='ko').translate(text)
        if result and len(result) >= 10:
            return result
        return None
    except Exception:
        return None


def get_target_vods(conn) -> list[dict]:
    """영어 smry를 가진 jikan VOD 조회"""
    query = """
        SELECT DISTINCT ON (smry) full_asset_id, smry
        FROM vod
        WHERE rag_source = 'jikan'
          AND smry IS NOT NULL
        ORDER BY smry, full_asset_id
    """
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
        # 영어인 것만 필터링
        return [
            {'full_asset_id': r[0], 'smry': r[1]}
            for r in rows
            if is_english(r[1])
        ]


def update_smry(conn, full_asset_id: str, smry_ko: str):
    query = "UPDATE vod SET smry = %s WHERE full_asset_id = %s"
    with conn.cursor() as cur:
        cur.execute(query, (smry_ko, full_asset_id))
    conn.commit()


def process_vod(vod: dict) -> tuple[str, bool]:
    pool = get_db_pool()
    conn = pool.getconn()
    try:
        time.sleep(0.2)  # Google Translate 요청 간격
        smry_ko = translate_to_ko(vod['smry'])
        if smry_ko:
            update_smry(conn, vod['full_asset_id'], smry_ko)
            return vod['full_asset_id'], True
        return vod['full_asset_id'], False
    except Exception as e:
        safe_print(f"  [오류] {vod['full_asset_id']}: {e}")
        try:
            conn.rollback()
        except:
            pass
        return vod['full_asset_id'], False
    finally:
        pool.putconn(conn)


def run(max_workers: int = 5):
    print('=' * 50)
    print('smry 영어 → 한국어 번역')
    print('=' * 50)

    conn = psycopg2.connect(**DB_CONFIG)
    vods = get_target_vods(conn)
    conn.close()

    total = len(vods)
    print(f'대상: {total:,}건 (영어 smry)\n')
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
    print(f'번역률: {success/total*100:.1f}%')


if __name__ == '__main__':
    run(max_workers=5)
