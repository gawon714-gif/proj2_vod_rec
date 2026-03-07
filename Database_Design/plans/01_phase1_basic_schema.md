# Phase 1: 기본 스키마 설계 - 완료

**상태**: 완료
**완료일**: 2026-03-06
**산출물**: `schema/create_tables.sql`, `schema/DESIGN.md`, `migration/migrate.py`

---

## 완료된 작업

### 1. DDL 스크립트 (`schema/create_tables.sql`)

3개 테이블 + 인덱스 + 파티셔닝 구현 완료.

#### VOD 테이블 (166,159개)
```
full_asset_id (PK), asset_nm, ct_cl, genre, provider, genre_detail, series_nm,
disp_rtm_sec, director (NULL 허용), smry (NULL 허용), asset_prod,
rag_processed, rag_source, rag_processed_at,
created_at, updated_at
```
- `pg_trgm` 확장으로 제목 LIKE 검색 최적화
- `rag_processed` 부분 인덱스로 RAG 미처리 레코드 빠른 조회

#### USERS 테이블 (242,702명)
```
sha2_hash (PK), age_grp10, inhome_rate, ch_hh_avg_month1,
svod_scrb_cnt_grp, paid_chnl_cnt_grp, kids_use_pv_month1, nfx_use_yn,
created_at, updated_at
```
- PostgreSQL 예약어 충돌 회피: `user` → `users`
- 구독 그룹은 원본 형식("0건","1건") VARCHAR로 보존

#### WATCH_HISTORY 테이블 (3,992,530건)
```
watch_history_id (PK + IDENTITY), user_id_fk, vod_id_fk,
strt_dt (파티션 키), use_tms, completion_rate, satisfaction
```
- `strt_dt` 기준 연도별 RANGE 파티셔닝: 2023, 2024, 2025, default
- 복합 PK `(watch_history_id, strt_dt)`: PostgreSQL 파티셔닝 제약 준수
- `satisfaction`: 베이지안 스코어 `(v*R + m*C)/(v+m)`, m=5.0

### 2. 인덱스 전략

| 인덱스 | 목적 |
|--------|------|
| `idx_wh_user_id` | 사용자별 시청이력 조회 (최빈 패턴) |
| `idx_wh_vod_id` | VOD별 통계 집계 |
| `idx_wh_strt_dt` | 날짜 범위 조회 + 파티션 프루닝 병행 |
| `idx_wh_satisfaction DESC` | 만족도 상위 VOD 순위 |
| `idx_wh_user_strt_dt` (복합) | 사용자별 최근 시청순 조회 |
| `idx_wh_unique_session` (UNIQUE) | 중복 시청 레코드 방지 |
| `idx_vod_asset_nm_trgm` (GIN) | 제목 부분 일치 LIKE 검색 |
| `idx_vod_rag_pending` (부분) | RAG 파이프라인용 미처리 레코드 |

### 3. 정규화 검증 (3NF)

- **VOD**: `full_asset_id` → 모든 컬럼 직접 종속. 이행 종속 없음.
- **USERS**: `sha2_hash` → 모든 컬럼 직접 종속. 이행 종속 없음.
- **WATCH_HISTORY**: `(watch_history_id, strt_dt)` → 모든 컬럼 직접 종속.

### 4. 마이그레이션 스크립트 (`migration/migrate.py`)

- SQLAlchemy + psycopg2 기반
- 배치 INSERT: 10,000행 단위
- WATCH_HISTORY: 청크 단위 읽기 (100,000행)
- ON CONFLICT DO NOTHING으로 중복 안전 처리
- 컬럼 변환:
  - `CT_CL` → `ct_cl` (대소문자 정규화)
  - `NFX_USE_YN` "Y"/"N" → Boolean
  - `director` "-" 값 → NULL
  - `strt_dt` → UTC timezone-aware

---

## 실행 방법

### 1단계: DDL 실행

```bash
# PostgreSQL DB 생성
psql -U postgres -c "CREATE DATABASE vod_recommendation;"

# DDL 스크립트 실행
psql -U postgres -d vod_recommendation -f schema/create_tables.sql
```

### 2단계: CSV 마이그레이션

```bash
# 의존성 설치
pip install pandas psycopg2-binary sqlalchemy tqdm

# migrate.py 내 DB_CONFIG 수정 후 실행
python migration/migrate.py
```

### 3단계: 데이터 검증

```sql
SELECT 'vod'           AS tbl, COUNT(*) AS rows FROM vod
UNION ALL
SELECT 'users',                 COUNT(*)         FROM users
UNION ALL
SELECT 'watch_history',         COUNT(*)         FROM watch_history;

-- 기대값:
--   vod:           166,159
--   users:         242,702
--   watch_history: 3,992,530
```

---

## 알려진 이슈 및 후속 작업

| 항목 | 내용 | 해결 Phase |
|------|------|----------|
| `director` NULL 313건 | RAG로 IMDB/Wiki 검색 후 보강 | Phase 2 |
| `smry` NULL 28건 | RAG로 줄거리 검색 후 보강 | Phase 2 |
| CSV 파일 경로 | `migrate.py`의 `CSV_DIR` 경로 확인 필요 | 실행 전 확인 |
| DB 비밀번호 | `migrate.py`의 `DB_CONFIG` 수정 필요 | 실행 전 확인 |
