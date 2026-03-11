"""
rating 값 정규화 (일회성)

다양한 소스에서 들어온 rating 표기를 통일된 형식으로 변환
전체이용가 / 7세이상 / 12세이상 / 15세이상 / 19세이상
"""

import os
import sys
import psycopg2
sys.stdout.reconfigure(encoding='utf-8')
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '../config/.env'))

DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', 5432),
    'dbname': os.getenv('DB_NAME', 'vod_recommendation'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD'),
}

RATING_MAP = {
    # 전체이용가
    '전체이용가': '전체이용가',
    'ALL':       '전체이용가',
    'G':         '전체이용가',
    'TV-G':      '전체이용가',
    'TV-Y':      '전체이용가',
    # 7세이상
    '7세이상':       '7세이상',
    '7세이상관람가':  '7세이상',
    '7':             '7세이상',
    'TV-Y7':         '7세이상',
    # 12세이상
    '12세이상':      '12세이상',
    '12세이상관람가': '12세이상',
    '12':            '12세이상',
    '12+':           '12세이상',
    'PG':            '12세이상',
    # 15세이상
    '15세이상':      '15세이상',
    '15세이상관람가': '15세이상',
    '15':            '15세이상',
    '15+':           '15세이상',
    # 19세이상
    '19세이상':      '19세이상',
    '18세이상관람가': '19세이상',
    '청소년관람불가':  '19세이상',
    '청소년 관람불가': '19세이상',
    '청소년 관람 불가': '19세이상',
    '청소년 관람불가 ': '19세이상',
    '연소자불가':     '19세이상',
    '제한상영가':     '19세이상',
    '19':            '19세이상',
    'R':             '19세이상',
    'NC-17':         '19세이상',
}


def run():
    print('=' * 50)
    print('rating 정규화')
    print('=' * 50)

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # 현재 분포 확인
    cur.execute('SELECT rating, COUNT(*) FROM vod WHERE rating IS NOT NULL GROUP BY rating ORDER BY COUNT(*) DESC')
    before = cur.fetchall()

    total_updated = 0
    for raw_rating, count in before:
        normalized = RATING_MAP.get(raw_rating)
        if normalized and normalized != raw_rating:
            cur.execute('UPDATE vod SET rating = %s WHERE rating = %s', (normalized, raw_rating))
            updated = cur.rowcount
            total_updated += updated
            print(f'  {raw_rating:20s} → {normalized:10s} ({updated:,}건)')
        elif not normalized:
            print(f'  {raw_rating:20s} → 매핑 없음 ({count:,}건) — 유지')

    conn.commit()

    # 정규화 후 분포
    cur.execute('SELECT rating, COUNT(*) FROM vod WHERE rating IS NOT NULL GROUP BY rating ORDER BY COUNT(*) DESC')
    after = cur.fetchall()

    print(f'\n총 {total_updated:,}건 정규화 완료')
    print('\n=== 정규화 후 rating 분포 ===')
    for r in after:
        print(f'  {str(r[0]):12s} {r[1]:,}건')

    conn.close()


if __name__ == '__main__':
    run()
