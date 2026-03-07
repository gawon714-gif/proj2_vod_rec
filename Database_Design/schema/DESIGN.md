# VOD 추천 시스템 - PostgreSQL 데이터베이스 설계 문서

**생성일**: 2026-03-06
**대상 DB**: PostgreSQL 15+
**데이터 규모**: 시청이력 3,992,530건 / 사용자 242,702명 / VOD 166,159개

---

## 1. 테이블 설계

### 1.1 VOD 테이블

| 컬럼 | 타입 | 제약조건 | 설명 |
|------|------|---------|------|
| full_asset_id | VARCHAR(64) | PK | 영상 고유 식별자 (provider\|assetId) |
| asset_nm | VARCHAR(255) | NOT NULL | 콘텐츠 제목 |
| ct_cl | VARCHAR(32) | NOT NULL | 대분류 (14개 유형) |
| genre | VARCHAR(64) | | 장르 (68개) |
| provider | VARCHAR(128) | | 제공사 (33개) |
| genre_detail | VARCHAR(255) | | 장르 상세 |
| series_nm | VARCHAR(255) | | 시리즈명 (단편은 NULL) |
| disp_rtm_sec | INTEGER | NOT NULL, >0 | 영상 길이(초), 평균 2,901초 |
| director | VARCHAR(255) | NULL 허용 | 감독명. 313건 누락 → RAG 보강 예정 |
| smry | TEXT | NULL 허용 | 줄거리. 28건 누락 → RAG 보강 예정 |
| asset_prod | VARCHAR(64) | | 제작/제공사 |
| rag_processed | BOOLEAN | DEFAULT FALSE | RAG 처리 완료 여부 |
| rag_source | VARCHAR(64) | | RAG 출처 (IMDB/WIKI 등) |
| rag_processed_at | TIMESTAMPTZ | | RAG 처리 시각 |
| created_at | TIMESTAMPTZ | NOT NULL | 레코드 생성 시각 |
| updated_at | TIMESTAMPTZ | NOT NULL | 레코드 수정 시각 (트리거 자동 갱신) |

**3NF 검증**: `full_asset_id` → 모든 컬럼 직접 종속. 이행 종속 없음.

**RAG 컬럼 설계 의도**:
`director`(NULL 313건)와 `smry`(NULL 28건)는 마이그레이션 후 RAG 파이프라인(IMDB/Wiki)으로 채울 예정. `rag_processed` 부분 인덱스로 미처리 레코드를 빠르게 조회.

---

### 1.2 USERS 테이블

| 컬럼 | 타입 | 제약조건 | 설명 |
|------|------|---------|------|
| sha2_hash | VARCHAR(64) | PK | SHA-256 해시된 사용자 ID (PII 보호) |
| age_grp10 | VARCHAR(16) | | 연령대 (10대~90대이상, 9개 그룹) |
| inhome_rate | REAL | 0~100 | 재택 시청 비율(%) |
| ch_hh_avg_month1 | REAL | | 월평균 TV 시청 시간(시간) |
| svod_scrb_cnt_grp | VARCHAR(16) | | SVOD 구독 건수 그룹 ("0건","1건" 등) |
| paid_chnl_cnt_grp | VARCHAR(16) | | 유료 채널 결제 건수 그룹 |
| kids_use_pv_month1 | REAL | | 키즈 콘텐츠 월 시청량(PV) |
| nfx_use_yn | BOOLEAN | | Netflix 사용 여부 (12.99% = 31,528명) |
| created_at | TIMESTAMPTZ | NOT NULL | 레코드 생성 시각 |
| updated_at | TIMESTAMPTZ | NOT NULL | 레코드 수정 시각 |

**3NF 검증**: `sha2_hash` → 모든 컬럼 직접 종속. 이행 종속 없음.

**`svod_scrb_cnt_grp` / `paid_chnl_cnt_grp` VARCHAR 선택 이유**:
원본 데이터가 "0건", "1건" 형식의 카테고리 문자열. 의미 손실 없이 원본 형식 보존.

---

### 1.3 WATCH_HISTORY 테이블 (파티셔닝)

| 컬럼 | 타입 | 제약조건 | 설명 |
|------|------|---------|------|
| watch_history_id | BIGINT | PK (IDENTITY) | 자동 생성 PK |
| user_id_fk | VARCHAR(64) | NOT NULL, FK→users | 사용자 외래키 |
| vod_id_fk | VARCHAR(64) | NOT NULL, FK→vod | VOD 외래키 |
| strt_dt | TIMESTAMPTZ | NOT NULL, PK 포함 | 시청 시작 시각 (파티션 키) |
| use_tms | REAL | NOT NULL, ≥0 | 실제 시청 시간(초) |
| completion_rate | DOUBLE PRECISION | 0~1 | 시청 완료율 (전체 평균 0.4676) |
| satisfaction | DOUBLE PRECISION | 0~1 | 베이지안 만족도 스코어 |

**3NF 검증**: PK `(watch_history_id, strt_dt)` → 모든 컬럼 직접 종속.
`satisfaction`은 베이지안 공식으로 사전 계산된 값을 저장 (실시간 재계산 비용 회피).

**DOUBLE PRECISION 선택 이유**:
`completion_rate` 원본값이 `0.0004115226337448` 수준의 정밀도를 가짐.
FLOAT/REAL(7자리)로는 정밀도 손실 발생 → DOUBLE PRECISION(15자리) 사용.

**만족도(Satisfaction) 계산 공식**:
```
satisfaction = (v * R + m * C) / (v + m)

v : 해당 VOD의 총 시청 건수
R : 해당 레코드의 시청 완료율 (use_tms / disp_rtm_sec)
C : 전체 VOD 평균 시청 완료율 (전역 상수)
m : 신뢰도 조절 파라미터 (기본값 5.0)

예외: use_tms ≤ 60초 → satisfaction = 0.0
```

---

## 2. 파티셔닝 설계

**방식**: `WATCH_HISTORY` 연도별 RANGE 파티셔닝 (`strt_dt` 기준)

```
watch_history (부모)
├── watch_history_2023  (2023-01-01 ~ 2023-12-31)
├── watch_history_2024  (2024-01-01 ~ 2024-12-31)
├── watch_history_2025  (2025-01-01 ~ 2025-12-31)
└── watch_history_default  (범위 외 데이터 보호)
```

**선택 이유**:
- 3.99M건 이상 데이터를 연도별 분할 → 날짜 범위 쿼리 파티션 프루닝 적용
- 추후 연도 파티션 추가만으로 수평 확장 가능
- PostgreSQL 제약: 파티션 테이블 PK에 파티션 키 포함 필수 → `(watch_history_id, strt_dt)` 복합 PK

---

## 3. 인덱싱 전략

| 인덱스 | 테이블 | 타입 | 목적 |
|--------|--------|------|------|
| idx_vod_ct_cl | vod | B-tree | 콘텐츠 유형별 필터링 |
| idx_vod_genre | vod | B-tree | 장르별 필터링 |
| idx_vod_provider | vod | B-tree | 제공사별 필터링 |
| idx_vod_asset_nm_trgm | vod | GIN (pg_trgm) | 제목 부분 일치 검색 |
| idx_vod_rag_pending | vod | 부분 B-tree | RAG 미처리 레코드 조회 |
| idx_users_age_grp10 | users | B-tree | 연령대 세그멘테이션 |
| idx_wh_user_id | watch_history | B-tree | 사용자별 시청이력 조회 |
| idx_wh_vod_id | watch_history | B-tree | VOD별 통계 집계 |
| idx_wh_strt_dt | watch_history | B-tree | 날짜 범위 조회 |
| idx_wh_satisfaction | watch_history | B-tree (DESC) | 만족도 상위 VOD 조회 |
| idx_wh_user_strt_dt | watch_history | 복합 B-tree | 사용자별 최근 시청순 조회 |
| idx_wh_unique_session | watch_history | UNIQUE | 중복 시청 레코드 방지 |

**핵심 인덱스 선택 근거**:
- `idx_wh_user_id`: 추천 시스템의 가장 빈번한 쿼리 패턴 (사용자별 시청이력)
- `idx_wh_user_strt_dt`: 복합 인덱스로 사용자별 + 날짜 범위 복합 조회 커버
- `idx_vod_asset_nm_trgm`: GIN 인덱스로 LIKE 검색 O(n) → O(log n) 최적화
- `idx_vod_rag_pending`: 부분 인덱스로 RAG 파이프라인 대상 레코드만 인덱싱

---

## 4. 성능 예측

| 쿼리 패턴 | 사용 인덱스 | 예상 성능 |
|-----------|------------|---------|
| 사용자별 시청이력 (WHERE user_id_fk = ?) | idx_wh_user_id | < 100ms |
| VOD별 시청 통계 (WHERE vod_id_fk = ?) | idx_wh_vod_id | < 100ms |
| 날짜 범위 조회 (WHERE strt_dt BETWEEN) | idx_wh_strt_dt + 파티션 프루닝 | < 500ms |
| 만족도 상위 VOD (ORDER BY satisfaction DESC) | idx_wh_satisfaction | < 200ms |
| 제목 검색 (LIKE '%검색어%') | idx_vod_asset_nm_trgm | < 50ms |

---

## 5. 확장 계획

**Phase 1 (현재)**: VOD, USERS, WATCH_HISTORY 기본 스키마
**Phase 2**: RAG 파이프라인 실행 → director, smry NULL 보강
**Phase 3**: pgvector 확장으로 VOD_EMBEDDING, USER_EMBEDDING 테이블 추가
**Phase 4**: VOD_RECOMMENDATION 캐시 테이블 추가 (TTL 7일)

```sql
-- Phase 3 예시: pgvector 임베딩 테이블
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE vod_embedding (
    vod_id_fk       VARCHAR(64) PRIMARY KEY REFERENCES vod(full_asset_id),
    embedding       vector(1536),    -- OpenAI text-embedding-3-large
    model_version   VARCHAR(64),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON vod_embedding USING ivfflat (embedding vector_cosine_ops);
```
