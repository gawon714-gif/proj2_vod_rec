# Phase 3: 벡터 임베딩 스키마 설계

**상태**: 대기 (Phase 2 완료 후 시작 권장)
**선행 조건**: Phase 1 완료. Phase 2는 임베딩 품질 향상을 위해 권장되나 필수는 아님.
**아키텍처**: PostgreSQL (메타데이터) + Milvus (실제 벡터)

---

## 목표

콘텐츠와 사용자의 벡터 임베딩을 생성·저장하는 스키마를 추가한다.
실제 고차원 벡터는 Milvus에, 메타데이터는 PostgreSQL에 저장하는 분리 아키텍처를 사용한다.

---

## 아키텍처 결정: Milvus vs pgvector

| 기준 | Milvus | pgvector (PostgreSQL) |
|------|--------|----------------------|
| 벡터 검색 속도 | O(log n) HNSW, 밀리초 | O(n) 기본, IVFFlat으로 보완 |
| 트랜잭션 | 미지원 | 완전 지원 |
| 운영 복잡도 | 별도 서버 필요 | PostgreSQL 확장 |
| 권장 규모 | 100만+ 벡터 | ~10만 벡터 |

**결정**: Milvus에 벡터 저장, PostgreSQL에 메타데이터 저장.
VOD 166,159개 × 임베딩 타입 최대 4개 = ~660,000 벡터 → Milvus 권장.

---

## DDL - VOD_EMBEDDING 테이블 추가

```sql
-- pgvector 확장 (향후 소규모 검색에 pgvector 활용 시 사용)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE vod_embedding (
    vod_embedding_id        BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 참조
    vod_id_fk               VARCHAR(64)     NOT NULL UNIQUE,

    -- Milvus 연동 메타데이터
    milvus_collection_id    VARCHAR(128),   -- Milvus 컬렉션명
    milvus_vector_id        BIGINT,         -- Milvus 내부 ID

    -- 임베딩 정보
    embedding_type          VARCHAR(32)     NOT NULL,
        -- 'METADATA'  : 텍스트 임베딩 (제목 + 줄거리 + 장르), 384차원
        -- 'VISUAL'    : 썸네일 이미지 임베딩, 512차원
        -- 'HYBRID'    : METADATA + VISUAL 결합, 896차원
    embedding_dimension     INTEGER         NOT NULL,
    embedding_model_version VARCHAR(64),    -- 예: 'text-embedding-3-small'

    -- 시간 정보
    created_at              TIMESTAMP WITH TIME ZONE    NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE    NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_vod_embedding_vod
        FOREIGN KEY (vod_id_fk) REFERENCES vod(full_asset_id) ON DELETE CASCADE,
    CONSTRAINT uq_vod_embedding_type
        UNIQUE (vod_id_fk, embedding_type)
);

CREATE TRIGGER vod_embedding_set_updated_at
    BEFORE UPDATE ON vod_embedding
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE INDEX idx_vod_emb_type    ON vod_embedding (embedding_type);
CREATE INDEX idx_vod_emb_updated ON vod_embedding (updated_at);

COMMENT ON TABLE  vod_embedding IS 'VOD 벡터 임베딩 메타데이터. 실제 벡터는 Milvus에 저장.';
COMMENT ON COLUMN vod_embedding.milvus_vector_id IS 'Milvus에서 반환된 벡터 ID. 검색 시 참조.';
```

---

## DDL - USER_EMBEDDING 테이블 추가

```sql
CREATE TABLE user_embedding (
    user_embedding_id       BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 참조
    user_id_fk              VARCHAR(64)     NOT NULL,

    -- Milvus 연동 메타데이터
    milvus_collection_id    VARCHAR(128),
    milvus_vector_id        BIGINT,

    -- 임베딩 정보
    embedding_type          VARCHAR(32)     NOT NULL,
        -- 'BEHAVIOR'      : 시청이력 기반, 256차원
        -- 'GENRE_PREF'    : 장르별 친화도, 128차원
        -- 'DEMOGRAPHIC'   : 인구통계 기반, 64차원
        -- 'HYBRID'        : 전체 결합, 448차원
    embedding_dimension     INTEGER         NOT NULL,
    embedding_model_version VARCHAR(64),

    -- 생성 기반 정보
    base_record_count       INTEGER,        -- 생성에 사용된 watch_history 건수

    -- 시간 정보
    created_at              TIMESTAMP WITH TIME ZONE    NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE    NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_user_embedding_user
        FOREIGN KEY (user_id_fk) REFERENCES users(sha2_hash) ON DELETE CASCADE,
    CONSTRAINT uq_user_embedding_type
        UNIQUE (user_id_fk, embedding_type)
);

CREATE TRIGGER user_embedding_set_updated_at
    BEFORE UPDATE ON user_embedding
    FOR EACH ROW EXECUTE FUNCTION trigger_set_updated_at();

CREATE INDEX idx_user_emb_type    ON user_embedding (embedding_type);
CREATE INDEX idx_user_emb_updated ON user_embedding (updated_at);

COMMENT ON TABLE  user_embedding IS '사용자 벡터 임베딩 메타데이터. 실제 벡터는 Milvus에 저장.';
COMMENT ON COLUMN user_embedding.base_record_count IS '임베딩 생성 시 사용된 시청이력 건수. 신뢰도 지표.';
```

---

## VOD 임베딩 입력 데이터

```sql
-- 임베딩 생성을 위한 VOD 텍스트 데이터 조회
SELECT
    full_asset_id,
    asset_nm,
    ct_cl,
    genre,
    genre_detail,
    director,
    smry,
    asset_prod
FROM vod
WHERE rag_processed = TRUE   -- RAG 보강 완료된 VOD 우선
   OR (director IS NOT NULL AND smry IS NOT NULL)
ORDER BY full_asset_id;
```

임베딩 입력 텍스트 구성 예시:
```
[제목] 완전한 사육: 욕망의 시작
[장르] 드라마 / 무료영화
[감독] 카토 타쿠야
[줄거리] 코이즈미 아야노는 아방가르드한 연출 스타일로 연극계에서 주목받는...
```

---

## USER 임베딩 생성 로직

```sql
-- 사용자별 최근 90일 시청 통계 (임베딩 입력)
SELECT
    wh.user_id_fk,
    v.genre,
    COUNT(*)                        AS watch_count,
    AVG(wh.completion_rate)         AS avg_completion,
    AVG(wh.satisfaction)            AS avg_satisfaction
FROM watch_history wh
JOIN vod v ON wh.vod_id_fk = v.full_asset_id
WHERE wh.strt_dt >= NOW() - INTERVAL '90 days'
GROUP BY wh.user_id_fk, v.genre
ORDER BY wh.user_id_fk, watch_count DESC;
```

---

## 완료 기준

- [ ] `vod_embedding` 테이블 생성 완료
- [ ] `user_embedding` 테이블 생성 완료
- [ ] Milvus 컬렉션 생성 (별도 Milvus 설정 작업)
- [ ] VOD 166,159개 METADATA 임베딩 생성 및 저장
- [ ] 활성 사용자 임베딩 생성 및 저장 (최소 HYBRID 타입)
- [ ] Milvus 코사인 유사도 검색 응답시간 < 100ms (Top-100 기준)
