# user_embedding 브랜치 작업 지침

**목표**: VOD 메타데이터 + 시청이력 기반 벡터 임베딩 생성 및 저장
**선행 조건**: RAG 파이프라인 완료 (vod.rag_processed 데이터 활용)
**브랜치**: user_embedding

---

## 아키텍처

```
PostgreSQL (메타데이터)         Milvus (실제 벡터)
  vod_embedding 테이블    ←→    vod_collection
  user_embedding 테이블   ←→    user_collection
```

- 실제 고차원 벡터는 Milvus에 저장 (검색 성능)
- 메타데이터(milvus_vector_id, embedding_type 등)는 PostgreSQL에 저장

---

## 데이터 규모

| 항목 | 수치 |
|------|------|
| VOD | 166,159개 |
| 사용자 | 242,702명 |
| 시청이력 | 3,992,530건 |

---

## 임베딩 타입 정의

### VOD 임베딩
| 타입 | 차원 | 입력 데이터 |
|------|------|------------|
| METADATA | 384 | 제목 + 줄거리 + 장르 + 감독 |
| VISUAL | 512 | 썸네일 이미지 (향후) |
| HYBRID | 896 | METADATA + VISUAL 결합 |

### USER 임베딩
| 타입 | 차원 | 입력 데이터 |
|------|------|------------|
| BEHAVIOR | 256 | 시청이력 (장르별 시청횟수, 완료율, 만족도) |
| GENRE_PREF | 128 | 장르별 친화도 벡터 |
| DEMOGRAPHIC | 64 | 연령대, 재택률, 구독정보 등 |
| HYBRID | 448 | BEHAVIOR + GENRE_PREF + DEMOGRAPHIC 결합 |

---

## DB 테이블 구조

### vod_embedding (PostgreSQL 메타데이터)
```sql
vod_embedding_id        BIGINT PK
vod_id_fk               VARCHAR(64) → vod.full_asset_id
milvus_collection_id    VARCHAR(128)
milvus_vector_id        BIGINT
embedding_type          VARCHAR(32)  -- METADATA / VISUAL / HYBRID
embedding_dimension     INTEGER
embedding_model_version VARCHAR(64)
created_at, updated_at  TIMESTAMPTZ
```

### user_embedding (PostgreSQL 메타데이터)
```sql
user_embedding_id       BIGINT PK
user_id_fk              VARCHAR(64) → users.sha2_hash
milvus_collection_id    VARCHAR(128)
milvus_vector_id        BIGINT
embedding_type          VARCHAR(32)  -- BEHAVIOR / GENRE_PREF / DEMOGRAPHIC / HYBRID
embedding_dimension     INTEGER
base_record_count       INTEGER      -- 사용된 watch_history 건수 (신뢰도 지표)
embedding_model_version VARCHAR(64)
created_at, updated_at  TIMESTAMPTZ
```

---

## 개발 방식 — TDD (Test Driven Development)

**모든 기능은 TDD 사이클로 개발:**
```
1. Red      → 실패하는 테스트 먼저 작성
2. Green    → 테스트를 통과하는 최소한의 코드 작성
3. Refactor → 코드 정리 (테스트는 계속 통과해야 함)
```

- 구현 코드 작성 전 반드시 테스트 파일에 실패 케이스 먼저 작성
- 테스트 없이 구현 코드만 작성하지 말 것
- 각 Phase 완료 시 `report-agent`로 진행상황 보고서 작성

---

## Agent 사용 규칙

| Agent | 역할 | 실행 시점 |
|-------|------|----------|
| `tdd-agent` | TDD 사이클 관리 | 새 기능 개발 시작 시 |
| `report-agent` | 진행상황 보고서 작성 | Phase 완료 시, 주요 기능 구현 시 |

- 보고서 저장 위치: `user_embedding/reports/YYYY-MM-DD_{작업명}.md`

---

## 파일 구조

```
user_embedding/
├── src/
│   ├── create_tables.sql        # vod_embedding, user_embedding DDL
│   ├── vod_embedding.py         # VOD 임베딩 생성
│   ├── user_embedding.py        # USER 임베딩 생성
│   └── milvus_client.py         # Milvus 연결 및 컬렉션 관리
├── models/
│   └── (모델 설정 파일, 버전 관리)
├── notebooks/
│   └── (실험/검증용 Jupyter 노트북)
├── tests/
│   ├── test_vod_embedding.py    # VOD 임베딩 테스트
│   ├── test_user_embedding.py   # USER 임베딩 테스트
│   ├── test_milvus_client.py    # Milvus 연결 테스트
│   └── test_similarity.py       # 유사도 검색 테스트
├── config/
│   └── .env                     # DB/Milvus 연결 정보
├── reports/
│   └── YYYY-MM-DD_{작업명}.md   # 진행상황 보고서
└── .claude/
    ├── claude.md                # 이 파일
    └── agents/
        ├── tdd-agent.md         # TDD 사이클 관리
        └── report-agent.md      # 보고서 작성
```

---

## VOD 임베딩 입력 쿼리

```sql
SELECT
    full_asset_id,
    asset_nm,
    ct_cl,
    genre,
    director,
    smry
FROM vod
WHERE rag_processed = TRUE
   OR (director IS NOT NULL AND smry IS NOT NULL)
ORDER BY full_asset_id;
```

임베딩 텍스트 구성:
```
[제목] {asset_nm}
[장르] {ct_cl} / {genre}
[감독] {director}
[줄거리] {smry}
```

---

## USER 임베딩 입력 쿼리

```sql
SELECT
    wh.user_id_fk,
    v.genre,
    COUNT(*)                AS watch_count,
    AVG(wh.completion_rate) AS avg_completion,
    AVG(wh.satisfaction)    AS avg_satisfaction
FROM watch_history wh
JOIN vod v ON wh.vod_id_fk = v.full_asset_id
WHERE wh.strt_dt >= NOW() - INTERVAL '90 days'
GROUP BY wh.user_id_fk, v.genre
ORDER BY wh.user_id_fk, watch_count DESC;
```

---

## 사용 라이브러리

| 라이브러리 | 용도 |
|-----------|------|
| sentence-transformers | 텍스트 → 벡터 변환 (로컬, 무료) |
| pymilvus | Milvus 연결 및 벡터 저장 |
| psycopg2 | PostgreSQL 메타데이터 저장 |
| python-dotenv | 환경변수 관리 |

---

## 보안 규칙

- `.env` 파일 절대 Read 툴로 열지 말 것
- Milvus 연결 정보, DB 비밀번호 코드에 하드코딩 금지
- 커밋 전 `/commit-check` 실행

---

## 작업 완료 기준

- [ ] vod_embedding, user_embedding 테이블 생성 완료
- [ ] Milvus 컬렉션 생성 (vod_collection, user_collection)
- [ ] VOD 166,159개 METADATA 임베딩 생성 및 저장
- [ ] 활성 사용자 HYBRID 임베딩 생성 및 저장
- [ ] 코사인 유사도 검색 응답시간 < 100ms (Top-100 기준)
- [ ] 작업 레포트 저장 (`reports/`)
