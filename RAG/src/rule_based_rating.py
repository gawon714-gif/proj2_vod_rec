"""
Rule-based rating 채우기 (일회성)

대상: rating IS NULL
로직: ct_cl + 제목 키워드 기반 분류
할루시네이션 없음 (선택지 외 값 절대 저장 안 함)
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

VALID_RATINGS = {'전체이용가', '7세이상', '12세이상', '15세이상', '19세이상'}

ADULT_KEYWORDS = ['19금', '성인', '야한', '에로', '불륜', '정사', '섹시', '농염']
KID_KEYWORDS   = ['뽀로로', '타요', '핑크퐁', '아기상어', '코코몽', '꼬마버스', '번개맨',
                   '파워레인저', '또봇', '헬로카봇', '라바', '슈퍼윙스', '시크릿쥬쥬']

CT_CL_MAP = {
    'TV애니메이션': '전체이용가',
    '교육':        '전체이용가',
    '우리동네':    '전체이용가',
    'TV드라마':    '15세이상',
    'TV 연예/오락': '15세이상',
    'TV 시사/교양': '15세이상',
    '다큐':        '15세이상',
    '라이프':      '15세이상',
    '스포츠':      '15세이상',
    '공연/음악':   '15세이상',
    '영화':        '15세이상',
    '기타':        '15세이상',
    '미분류':      '15세이상',
}


def rule_based_rating(asset_nm: str, ct_cl: str) -> str | None:
    # 19세 키워드 우선
    for kw in ADULT_KEYWORDS:
        if kw in asset_nm:
            return '19세이상'
    # 키즈 키워드
    for kw in KID_KEYWORDS:
        if kw in asset_nm:
            return '전체이용가'
    # ct_cl 매핑
    rating = CT_CL_MAP.get(ct_cl)
    # 유효성 검증 (할루시네이션 방지)
    if rating not in VALID_RATINGS:
        return None
    return rating


def run():
    print('=' * 50)
    print('Rule-based rating 채우기')
    print('=' * 50)

    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    cur.execute('SELECT COUNT(*) FROM vod WHERE rating IS NULL')
    total = cur.fetchone()[0]
    print(f'대상: {total:,}건\n')

    cur.execute('SELECT full_asset_id, asset_nm, ct_cl FROM vod WHERE rating IS NULL')
    rows = cur.fetchall()

    success, skip = 0, 0
    for full_asset_id, asset_nm, ct_cl in rows:
        rating = rule_based_rating(asset_nm or '', ct_cl or '')
        if rating:
            cur.execute(
                'UPDATE vod SET rating = %s WHERE full_asset_id = %s',
                (rating, full_asset_id)
            )
            success += 1
        else:
            skip += 1

        if (success + skip) % 10000 == 0:
            conn.commit()
            done = success + skip
            print(f'[진행] {done:,}/{total:,} ({done/total*100:.1f}%) | 채움:{success:,} 스킵:{skip:,}')

    conn.commit()
    conn.close()

    print(f'\n완료: 채움 {success:,} / 스킵 {skip:,} / 전체 {total:,}')
    print(f'채움률: {success/total*100:.1f}%')


if __name__ == '__main__':
    run()
