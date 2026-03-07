# Phase 2: RAG 파이프라인 - NULL 컬럼 보강

**상태**: 대기 (Phase 1 완료 후 시작)
**선행 조건**: Phase 1 마이그레이션 완료 (PostgreSQL에 VOD 테이블 로드됨)
**협업 브랜치**: RAG 브랜치

---

## 목표

VOD 테이블의 NULL 컬럼을 RAG(Retrieval-Augmented Generation)로 자동 채우고,
`rag_processed` 플래그를 업데이트한다.

---

## 대상 컬럼

| 컬럼 | NULL 건수 | 비율 | RAG 소스 | 우선순위 |
|------|-----------|------|---------|---------|
| `director` | 313건 | 0.19% | IMDB / Wikipedia | HIGH |
| `smry` | 28건 | 0.017% | IMDB / Wikipedia | MEDIUM |

---

## DB 스키마 - RAG 추적 컬럼 (이미 Phase 1에서 설계됨)

```sql
-- vod 테이블에 이미 존재
rag_processed       BOOLEAN  NOT NULL DEFAULT FALSE
rag_source          VARCHAR(64)             -- 'IMDB', 'WIKI', 'MANUAL' 등
rag_processed_at    TIMESTAMP WITH TIME ZONE
```

---

## RAG 처리 대상 조회 쿼리

```sql
-- director가 NULL인 VOD 목록
SELECT full_asset_id, asset_nm, ct_cl, genre
FROM vod
WHERE rag_processed = FALSE
  AND director IS NULL
ORDER BY full_asset_id;

-- smry가 NULL인 VOD 목록
SELECT full_asset_id, asset_nm, ct_cl, genre
FROM vod
WHERE rag_processed = FALSE
  AND smry IS NULL
ORDER BY full_asset_id;

-- 전체 미처리 건수 (부분 인덱스 idx_vod_rag_pending 사용)
SELECT COUNT(*) FROM vod WHERE rag_processed = FALSE;
```

---

## RAG 처리 후 업데이트 쿼리

```sql
-- director 보강 후 업데이트
UPDATE vod
SET
    director         = :director_value,
    rag_processed    = TRUE,
    rag_source       = 'IMDB',
    rag_processed_at = NOW()
WHERE full_asset_id = :asset_id;

-- smry 보강 후 업데이트
UPDATE vod
SET
    smry             = :smry_value,
    rag_processed    = TRUE,
    rag_source       = 'WIKI',
    rag_processed_at = NOW()
WHERE full_asset_id = :asset_id;

-- director + smry 동시 보강
UPDATE vod
SET
    director         = :director_value,
    smry             = :smry_value,
    rag_processed    = TRUE,
    rag_source       = :rag_source,
    rag_processed_at = NOW()
WHERE full_asset_id = :asset_id;
```

---

## Python 연동 인터페이스 (RAG 브랜치 참고)

RAG 파이프라인에서 아래 함수 형태로 DB 업데이트 호출:

```python
from sqlalchemy import create_engine, text

def update_vod_rag_result(engine, asset_id: str, director: str = None,
                           smry: str = None, source: str = "IMDB"):
    """RAG 처리 결과를 VOD 테이블에 업데이트"""
    updates = {"rag_processed": True, "rag_source": source,
               "rag_processed_at": "NOW()"}
    if director:
        updates["director"] = director
    if smry:
        updates["smry"] = smry

    set_clause = ", ".join(f"{k} = :{k}" for k in updates)
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE vod SET {set_clause} WHERE full_asset_id = :asset_id"),
            {**updates, "asset_id": asset_id}
        )


def get_rag_pending_vods(engine) -> list[dict]:
    """RAG 미처리 VOD 목록 조회 (부분 인덱스 활용)"""
    with engine.connect() as conn:
        result = conn.execute(
            text("""
                SELECT full_asset_id, asset_nm, ct_cl, genre,
                       director, smry
                FROM vod
                WHERE rag_processed = FALSE
                  AND (director IS NULL OR smry IS NULL)
                ORDER BY full_asset_id
            """)
        )
        return [dict(row) for row in result]
```

---

## 검증 쿼리

```sql
-- RAG 처리 진행 현황
SELECT
    rag_processed,
    rag_source,
    COUNT(*) AS cnt
FROM vod
GROUP BY rag_processed, rag_source
ORDER BY rag_processed, rag_source;

-- 보강 완료율
SELECT
    ROUND(100.0 * SUM(CASE WHEN director IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2)
        AS director_fill_rate,
    ROUND(100.0 * SUM(CASE WHEN smry IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 2)
        AS smry_fill_rate
FROM vod;

-- 기대 완료율: director 95%+, smry 80%+
```

---

## 완료 기준

- [ ] `director` NULL 건수 313건 중 95% 이상 보강 (~297건)
- [ ] `smry` NULL 건수 28건 중 80% 이상 보강 (~22건)
- [ ] `rag_processed = TRUE` 건수 = 처리된 전체 건수
- [ ] `rag_processed_at` 타임스탬프 정상 기록
