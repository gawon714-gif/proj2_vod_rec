"""
VOD 추천 시스템 - CSV → PostgreSQL 마이그레이션 스크립트
대상: PostgreSQL 15+
생성일: 2026-03-06

실행 전 준비:
    pip install pandas psycopg2-binary sqlalchemy tqdm

실행 방법:
    python migrate.py

DB 연결 정보는 하단 DB_CONFIG를 수정하세요.
"""

import os
import math
import pandas as pd
from datetime import timezone
from sqlalchemy import create_engine, text
from tqdm import tqdm

# =============================================================================
# 설정
# =============================================================================

DB_CONFIG = {
    "host":     "localhost",
    "port":     5432,
    "dbname":   "vod_recommendation",   # 미리 CREATE DATABASE로 생성 필요
    "user":     "postgres",
    "password": "1248",
}

CSV_DIR = r"C:\Users\user\Downloads"

FILES = {
    "vod":           os.path.join(CSV_DIR, "vod_table.csv"),
    "users":         os.path.join(CSV_DIR, "user_table.csv"),
    "watch_history": os.path.join(CSV_DIR, "watch_history_table.csv"),
}

BATCH_SIZE = 10_000   # 한 번에 INSERT할 행 수

# =============================================================================
# DB 연결
# =============================================================================

def get_engine():
    url = (
        f"postgresql+psycopg2://{DB_CONFIG['user']}:{DB_CONFIG['password']}"
        f"@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['dbname']}"
    )
    return create_engine(url, pool_pre_ping=True)


# =============================================================================
# VOD 변환 로직
# =============================================================================

def transform_vod(df: pd.DataFrame) -> pd.DataFrame:
    """
    원본 컬럼 → DB 컬럼 변환
    원본: full_asset_id, asset_nm, CT_CL, disp_rtm, disp_rtm_sec,
          genre, director, asset_prod, smry, provider, genre_detail, series_nm
    """
    out = pd.DataFrame()

    out["full_asset_id"] = df["full_asset_id"].astype(str).str.strip()
    out["asset_nm"]      = df["asset_nm"].astype(str).str.strip()
    out["ct_cl"]         = df["CT_CL"].astype(str).str.strip()
    out["genre"]         = df["genre"].astype(str).str.strip().replace({"nan": None, "-": None})
    out["provider"]      = df["provider"].astype(str).str.strip().replace({"nan": None})
    out["genre_detail"]  = df["genre_detail"].astype(str).str.strip().replace({"nan": None})
    out["series_nm"]     = df["series_nm"].astype(str).str.strip().replace({"nan": None})

    # disp_rtm_sec: float → int (반올림). NaN은 0으로 처리 (RAG로 추후 보강 예정)
    out["disp_rtm_sec"]  = pd.to_numeric(df["disp_rtm_sec"], errors="coerce").fillna(0).round().astype(int)

    # director: "-" 또는 빈값 → None
    director = df["director"].astype(str).str.strip()
    out["director"] = director.where(~director.isin(["", "-", "nan"]), other=None)

    # smry: 빈값 → None
    smry = df["smry"].astype(str).str.strip()
    out["smry"] = smry.where(~smry.isin(["", "nan"]), other=None)

    out["asset_prod"]     = df["asset_prod"].astype(str).str.strip().replace({"nan": None})
    out["rag_processed"]  = False

    return out


# =============================================================================
# USERS 변환 로직
# =============================================================================

def transform_users(df: pd.DataFrame) -> pd.DataFrame:
    """
    원본 컬럼 → DB 컬럼 변환
    원본: sha2_hash, AGE_GRP10, INHOME_RATE, SVOD_SCRB_CNT_GRP,
          PAID_CHNL_CNT_GRP, CH_HH_AVG_MONTH1, KIDS_USE_PV_MONTH1, NFX_USE_YN
    """
    out = pd.DataFrame()

    out["sha2_hash"]            = df["sha2_hash"].astype(str).str.strip()
    out["age_grp10"]            = df["AGE_GRP10"].astype(str).str.strip().replace({"nan": None})
    out["inhome_rate"]          = pd.to_numeric(df["INHOME_RATE"], errors="coerce")
    out["ch_hh_avg_month1"]     = pd.to_numeric(df["CH_HH_AVG_MONTH1"], errors="coerce")
    out["svod_scrb_cnt_grp"]    = df["SVOD_SCRB_CNT_GRP"].astype(str).str.strip().replace({"nan": None})
    out["paid_chnl_cnt_grp"]    = df["PAID_CHNL_CNT_GRP"].astype(str).str.strip().replace({"nan": None})
    out["kids_use_pv_month1"]   = pd.to_numeric(df["KIDS_USE_PV_MONTH1"], errors="coerce")

    # NFX_USE_YN: "Y"/"N" → True/False
    nfx = df["NFX_USE_YN"].astype(str).str.strip().str.upper()
    out["nfx_use_yn"] = nfx.map({"Y": True, "N": False})

    return out


# =============================================================================
# WATCH_HISTORY 변환 로직
# =============================================================================

def transform_watch_history(df: pd.DataFrame) -> pd.DataFrame:
    """
    원본 컬럼 → DB 컬럼 변환
    원본: sha2_hash, full_asset_id, strt_dt, use_tms, completion_rate, satisfaction
    """
    out = pd.DataFrame()

    out["user_id_fk"] = df["sha2_hash"].astype(str).str.strip()
    out["vod_id_fk"]  = df["full_asset_id"].astype(str).str.strip()

    # strt_dt: timezone-aware로 변환
    out["strt_dt"] = pd.to_datetime(df["strt_dt"], errors="coerce").dt.tz_localize("UTC")

    out["use_tms"]         = pd.to_numeric(df["use_tms"], errors="coerce")
    out["completion_rate"] = pd.to_numeric(df["completion_rate"], errors="coerce").clip(0, 1)
    out["satisfaction"]    = pd.to_numeric(df["satisfaction"], errors="coerce").clip(0, 1)

    # strt_dt가 NULL인 행 제거 (파티셔닝 키는 NOT NULL이어야 함)
    out = out.dropna(subset=["strt_dt"])

    return out


# =============================================================================
# 배치 INSERT 헬퍼
# =============================================================================

def _nan_to_none(v):
    """float NaN을 None(NULL)으로 변환. psycopg2가 float NaN을 PostgreSQL NaN으로 전달하는 문제 방지."""
    if isinstance(v, float) and math.isnan(v):
        return None
    return v


def insert_batches(engine, table_name: str, df: pd.DataFrame, batch_size: int = BATCH_SIZE):
    total = len(df)
    n_batches = math.ceil(total / batch_size)

    print(f"  {table_name}: {total:,}행 → {n_batches}배치로 INSERT")

    for i in tqdm(range(n_batches), desc=f"  {table_name}"):
        batch = df.iloc[i * batch_size : (i + 1) * batch_size]
        # NaN → None 변환 (float NaN은 .where()로 처리 안 되므로 명시적 변환)
        records = [{k: _nan_to_none(v) for k, v in row.items()}
                   for row in batch.to_dict("records")]
        with engine.begin() as conn:
            conn.execute(
                text(f"INSERT INTO {table_name} ({', '.join(batch.columns)}) "
                     f"VALUES ({', '.join(':' + c for c in batch.columns)}) "
                     f"ON CONFLICT DO NOTHING"),
                records,
            )


# =============================================================================
# 메인
# =============================================================================

def main():
    print("=" * 60)
    print("VOD 추천 시스템 - PostgreSQL 마이그레이션")
    print("=" * 60)

    engine = get_engine()

    # DB 연결 확인
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print("[OK] DB 연결 성공\n")

    # ------------------------------------------------------------------
    # 1. VOD
    # ------------------------------------------------------------------
    print("[1/3] VOD 테이블 마이그레이션...")
    vod_df = pd.read_csv(FILES["vod"], low_memory=False)
    print(f"  원본: {len(vod_df):,}행 로드")
    vod_transformed = transform_vod(vod_df)
    insert_batches(engine, "vod", vod_transformed)
    print("  [완료]\n")

    # ------------------------------------------------------------------
    # 2. USERS
    # ------------------------------------------------------------------
    print("[2/3] USERS 테이블 마이그레이션...")
    users_df = pd.read_csv(FILES["users"], low_memory=False)
    print(f"  원본: {len(users_df):,}행 로드")
    users_transformed = transform_users(users_df)
    insert_batches(engine, "users", users_transformed)
    print("  [완료]\n")

    # ------------------------------------------------------------------
    # 3. WATCH_HISTORY
    # ------------------------------------------------------------------
    print("[3/3] WATCH_HISTORY 테이블 마이그레이션...")
    print("  (대용량 파일: 청크 단위로 읽습니다)")

    chunk_size = 100_000
    total_inserted = 0

    for chunk in tqdm(
        pd.read_csv(FILES["watch_history"], chunksize=chunk_size, low_memory=False),
        desc="  watch_history 청크",
    ):
        transformed = transform_watch_history(chunk)
        insert_batches(engine, "watch_history", transformed, batch_size=BATCH_SIZE)
        total_inserted += len(transformed)

    print(f"  총 {total_inserted:,}행 INSERT 완료\n")

    # ------------------------------------------------------------------
    # 검증
    # ------------------------------------------------------------------
    print("=" * 60)
    print("[검증] 테이블별 행 수 확인")
    print("=" * 60)
    with engine.connect() as conn:
        for table in ("vod", "users", "watch_history"):
            count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
            print(f"  {table:20s}: {count:>12,}행")

    print("\n마이그레이션 완료.")


if __name__ == "__main__":
    main()
