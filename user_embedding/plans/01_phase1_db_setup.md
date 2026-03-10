# Phase 1: DB 테이블 생성 + Milvus 컬렉션 셋업

**상태**: 대기
**선행 조건**: PostgreSQL vod, users, watch_history 테이블 존재

---

## 목표

vod_embedding, user_embedding 테이블을 PostgreSQL에 추가하고
Milvus에 벡터 저장용 컬렉션을 생성한다.

---

## DDL — vod_embedding

```sql
CREATE TABLE vod_embedding (
    vod_embedding_id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    vod_id_fk               VARCHAR(64)  NOT NULL UNIQUE,
    milvus_collection_id    VARCHAR(128),
    milvus_vector_id        BIGINT,
    embedding_type          VARCHAR(32)  NOT NULL,
        -- 'METADATA' : 제목+줄거리+장르, 384차원
        -- 'VISUAL'   : 썸네일 이미지, 512차원 (향후)
        -- 'HYBRID'   : METADATA+VISUAL, 896차원
    embedding_dimension     INTEGER      NOT NULL,
    embedding_model_version VARCHAR(64),
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_vod_embedding_vod
        FOREIGN KEY (vod_id_fk) REFERENCES vod(full_asset_id) ON DELETE CASCADE,
    CONSTRAINT uq_vod_embedding_type
        UNIQUE (vod_id_fk, embedding_type)
);

CREATE INDEX idx_vod_emb_type    ON vod_embedding (embedding_type);
CREATE INDEX idx_vod_emb_updated ON vod_embedding (updated_at);
```

---

## DDL — user_embedding

```sql
CREATE TABLE user_embedding (
    user_embedding_id       BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id_fk              VARCHAR(64)  NOT NULL,
    milvus_collection_id    VARCHAR(128),
    milvus_vector_id        BIGINT,
    embedding_type          VARCHAR(32)  NOT NULL,
        -- 'BEHAVIOR'    : 시청이력 기반, 256차원
        -- 'GENRE_PREF'  : 장르별 친화도, 128차원
        -- 'DEMOGRAPHIC' : 인구통계 기반, 64차원
        -- 'HYBRID'      : 전체 결합, 448차원
    embedding_dimension     INTEGER      NOT NULL,
    base_record_count       INTEGER,
    embedding_model_version VARCHAR(64),
    created_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT fk_user_embedding_user
        FOREIGN KEY (user_id_fk) REFERENCES users(sha2_hash) ON DELETE CASCADE,
    CONSTRAINT uq_user_embedding_type
        UNIQUE (user_id_fk, embedding_type)
);

CREATE INDEX idx_user_emb_type    ON user_embedding (embedding_type);
CREATE INDEX idx_user_emb_updated ON user_embedding (updated_at);
```

---

## Milvus 컬렉션 구성

| 컬렉션 | 차원 | 거리 측정 | 대상 |
|--------|------|----------|------|
| vod_collection | 384 | 코사인 유사도 | VOD METADATA 임베딩 |
| user_collection | 448 | 코사인 유사도 | USER HYBRID 임베딩 |

---

## 완료 기준

- [ ] vod_embedding 테이블 생성
- [ ] user_embedding 테이블 생성
- [ ] Milvus vod_collection 생성
- [ ] Milvus user_collection 생성
- [ ] DB 연결 및 Milvus 연결 테스트 통과
