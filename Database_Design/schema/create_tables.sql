-- =============================================================================
-- VOD 추천 시스템 - PostgreSQL DDL
-- 대상: PostgreSQL 15+
-- 생성일: 2026-03-06
--
-- 데이터 규모 (2023-01 기준):
--   - 시청이력: 3,992,530건
--   - 고유 사용자: 242,702명
--   - 고유 VOD: 166,159개
-- =============================================================================

CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- 제목 LIKE 검색 최적화용

-- =============================================================================
-- 유틸리티: updated_at 자동 갱신 트리거 함수
-- =============================================================================
CREATE OR REPLACE FUNCTION trigger_set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;


-- =============================================================================
-- 1. VOD 테이블
--    콘텐츠 고유 메타데이터. 166,159개.
--    3NF 검증: full_asset_id → 모든 컬럼 직접 종속, 이행 종속 없음.
-- =============================================================================
CREATE TABLE vod (
    -- 식별자
    full_asset_id       VARCHAR(64)     PRIMARY KEY,

    -- 기본 메타데이터
    asset_nm            VARCHAR(255)    NOT NULL,
    ct_cl               VARCHAR(32)     NOT NULL,       -- 대분류 (14개 유형)
    genre               VARCHAR(64),
    provider            VARCHAR(128),
    genre_detail        VARCHAR(255),
    series_nm           VARCHAR(255),

    -- 기술 사양
    disp_rtm_sec        INTEGER         NOT NULL CHECK (disp_rtm_sec >= 0),  -- 0: 재생시간 미상 (RAG 보강 예정)

    -- 제작진 (NULL 허용: RAG 파이프라인 보강 예정)
    director            VARCHAR(255),                   -- 313건 누락
    cast_lead           TEXT,                           -- 주연배우 JSON 배열. RAG 보강 예정
    cast_guest          TEXT,                           -- 조연배우 JSON 배열. RAG 보강 예정

    -- 분류/시간 정보 (NULL 허용: RAG 파이프라인 보강 예정)
    rating              VARCHAR(16),                    -- 연령등급 (전체이용가, 12세이상 등). RAG 보강 예정
    release_date        DATE,                           -- 개봉일. RAG 보강 예정

    -- 설명 (NULL 허용: RAG 파이프라인 보강 예정)
    smry                TEXT,                           -- 28건 누락

    -- 비즈니스 정보
    asset_prod          VARCHAR(64),

    -- RAG 처리 추적
    rag_processed       BOOLEAN         NOT NULL DEFAULT FALSE,
    rag_source          VARCHAR(64),
    rag_processed_at    TIMESTAMP WITH TIME ZONE,

    -- 레코드 메타데이터
    created_at          TIMESTAMP WITH TIME ZONE    NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMP WITH TIME ZONE    NOT NULL DEFAULT NOW()
);

CREATE TRIGGER vod_set_updated_at
    BEFORE UPDATE ON vod
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

COMMENT ON TABLE  vod               IS 'VOD 콘텐츠 메타데이터. 166,159개.';
COMMENT ON COLUMN vod.full_asset_id IS '영상 고유 식별자. 형식: provider|assetId (예: cjc|M4996864LFOL10619201)';
COMMENT ON COLUMN vod.ct_cl         IS '콘텐츠 대분류. 14개 유형 (영화, 드라마, 라이프 등)';
COMMENT ON COLUMN vod.disp_rtm_sec  IS '영상 전체 재생 시간(초). 평균 2,901초(약 48분)';
COMMENT ON COLUMN vod.director      IS 'NULL 허용. RAG(IMDB/Wiki)로 보강 예정. 313건 누락.';
COMMENT ON COLUMN vod.smry          IS 'NULL 허용. RAG(IMDB/Wiki)로 보강 예정. 28건 누락.';
COMMENT ON COLUMN vod.rag_processed IS 'RAG 파이프라인 처리 완료 여부';


-- =============================================================================
-- 2. USERS 테이블
--    사용자 인구통계 및 행동 패턴. 242,702명.
--    NOTE: "user"는 PostgreSQL 예약어이므로 "users"로 명명.
--    3NF 검증: sha2_hash → 모든 컬럼 직접 종속, 이행 종속 없음.
-- =============================================================================
CREATE TABLE users (
    -- 식별자
    sha2_hash               VARCHAR(64)     PRIMARY KEY,

    -- 인구통계
    age_grp10               VARCHAR(16),            -- 9개 그룹 (10대~90대이상)

    -- 행동 패턴
    inhome_rate             REAL    CHECK (inhome_rate >= 0 AND inhome_rate <= 100),
    ch_hh_avg_month1        REAL,                   -- 월평균 TV 시청 시간(시간)

    -- 구독 현황 (원본 형식 보존: "0건", "1건" 등)
    svod_scrb_cnt_grp       VARCHAR(16),
    paid_chnl_cnt_grp       VARCHAR(16),

    -- 특화 콘텐츠
    kids_use_pv_month1      REAL,                   -- 키즈 콘텐츠 월 시청량(PV)

    -- 외부 서비스
    nfx_use_yn              BOOLEAN,                -- Netflix 사용 여부

    -- 레코드 메타데이터
    created_at              TIMESTAMP WITH TIME ZONE    NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE    NOT NULL DEFAULT NOW()
);

CREATE TRIGGER users_set_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

COMMENT ON TABLE  users                     IS '사용자 인구통계 및 행동 패턴. 242,702명. SHA-2 해시로 PII 보호.';
COMMENT ON COLUMN users.sha2_hash           IS 'SHA-256 해시된 사용자 식별자. 64자. 양방향 복호화 불가.';
COMMENT ON COLUMN users.age_grp10           IS '10세 단위 연령대. 9개 그룹.';
COMMENT ON COLUMN users.inhome_rate         IS '재택 시청 비율 0~100%.';
COMMENT ON COLUMN users.svod_scrb_cnt_grp   IS 'SVOD 구독 건수 그룹. 원본 형식 유지 ("0건","1건" 등).';
COMMENT ON COLUMN users.paid_chnl_cnt_grp   IS '유료 채널 결제 건수 그룹. 원본 형식 유지.';
COMMENT ON COLUMN users.nfx_use_yn          IS 'Netflix 병행 사용 여부. TRUE = 12.99%(31,528명).';


-- =============================================================================
-- 3. WATCH_HISTORY 테이블 (연도별 범위 파티셔닝)
--    사용자-콘텐츠 시청 이력. 3,992,530건.
--    3NF 검증: PK(watch_history_id, strt_dt) → 모든 컬럼 직접 종속.
--              satisfaction은 외부 계산값(베이지안 스코어)으로 저장.
--
--    파티셔닝 이유:
--      - 3.99M건 이상 데이터를 연도별로 분할해 조회 성능 향상
--      - 파티션 프루닝으로 날짜 범위 쿼리 최적화
--      - PostgreSQL 제약: PK에 파티션 키(strt_dt) 포함 필수
-- =============================================================================
CREATE TABLE watch_history (
    -- 식별자
    watch_history_id    BIGINT      GENERATED ALWAYS AS IDENTITY,

    -- 외래키
    user_id_fk          VARCHAR(64)     NOT NULL,
    vod_id_fk           VARCHAR(64)     NOT NULL,

    -- 시간 정보
    strt_dt             TIMESTAMP WITH TIME ZONE    NOT NULL,

    -- 재생 통계
    use_tms             REAL            NOT NULL CHECK (use_tms >= 0),
    completion_rate     DOUBLE PRECISION    CHECK (completion_rate >= 0 AND completion_rate <= 1),
    satisfaction        DOUBLE PRECISION    CHECK (satisfaction >= 0 AND satisfaction <= 1),

    -- 복합 PK: 파티션 키(strt_dt) 포함 필수
    PRIMARY KEY (watch_history_id, strt_dt),

    CONSTRAINT fk_watch_user
        FOREIGN KEY (user_id_fk) REFERENCES users(sha2_hash)       ON DELETE CASCADE,
    CONSTRAINT fk_watch_vod
        FOREIGN KEY (vod_id_fk)  REFERENCES vod(full_asset_id)      ON DELETE CASCADE

) PARTITION BY RANGE (strt_dt);

COMMENT ON TABLE  watch_history                 IS '시청 이력. 3,992,530건. strt_dt 기준 연도별 파티셔닝.';
COMMENT ON COLUMN watch_history.use_tms         IS '실제 시청 시간(초). 60초 이하는 만족도 0점 처리.';
COMMENT ON COLUMN watch_history.completion_rate IS '시청 완료율 (0.0~1.0). 전체 평균 0.4676.';
COMMENT ON COLUMN watch_history.satisfaction    IS '베이지안 만족도: (v*R + m*C)/(v+m), m=5.0. 범위 0.0~1.0.';

-- 연도별 파티션
CREATE TABLE watch_history_2023
    PARTITION OF watch_history
    FOR VALUES FROM ('2023-01-01 00:00:00+00') TO ('2024-01-01 00:00:00+00');

CREATE TABLE watch_history_2024
    PARTITION OF watch_history
    FOR VALUES FROM ('2024-01-01 00:00:00+00') TO ('2025-01-01 00:00:00+00');

CREATE TABLE watch_history_2025
    PARTITION OF watch_history
    FOR VALUES FROM ('2025-01-01 00:00:00+00') TO ('2026-01-01 00:00:00+00');

-- 범위 초과 데이터 보호용 기본 파티션
CREATE TABLE watch_history_default
    PARTITION OF watch_history DEFAULT;


-- =============================================================================
-- 인덱스
-- 파티셔닝된 테이블 인덱스는 모든 파티션에 자동 전파 (PostgreSQL 11+)
-- =============================================================================

-- VOD 인덱스
CREATE INDEX idx_vod_ct_cl
    ON vod (ct_cl);
    -- 목적: 콘텐츠 유형별 필터링 (14개 유형)

CREATE INDEX idx_vod_genre
    ON vod (genre);
    -- 목적: 장르별 필터링 (68개 장르)

CREATE INDEX idx_vod_provider
    ON vod (provider);
    -- 목적: 제공사별 필터링 (33개 제공사)

CREATE INDEX idx_vod_asset_nm_trgm
    ON vod USING GIN (asset_nm gin_trgm_ops);
    -- 목적: 제목 부분 일치 검색 (LIKE '%검색어%' 최적화)

CREATE INDEX idx_vod_rag_pending
    ON vod (rag_processed)
    WHERE rag_processed = FALSE;
    -- 목적: RAG 파이프라인이 미처리 레코드 빠르게 조회 (부분 인덱스)

-- USERS 인덱스
CREATE INDEX idx_users_age_grp10
    ON users (age_grp10);
    -- 목적: 연령대별 세그멘테이션 (콜드스타트 추천)

-- WATCH_HISTORY 인덱스 (파티션 전파)
CREATE INDEX idx_wh_user_id
    ON watch_history (user_id_fk);
    -- 목적: 사용자별 시청이력 조회 (가장 빈번한 쿼리 패턴)

CREATE INDEX idx_wh_vod_id
    ON watch_history (vod_id_fk);
    -- 목적: VOD별 시청 통계 집계

CREATE INDEX idx_wh_strt_dt
    ON watch_history (strt_dt);
    -- 목적: 날짜 범위 조회 (파티션 프루닝과 병행)

CREATE INDEX idx_wh_satisfaction
    ON watch_history (satisfaction DESC NULLS LAST);
    -- 목적: 만족도 상위 VOD 조회

CREATE INDEX idx_wh_user_strt_dt
    ON watch_history (user_id_fk, strt_dt DESC);
    -- 목적: 사용자별 최근 시청순 복합 조회 (추천 feature 추출)

CREATE UNIQUE INDEX idx_wh_unique_session
    ON watch_history (user_id_fk, vod_id_fk, strt_dt);
    -- 목적: 동일 사용자-VOD-시작시각 중복 삽입 방지
