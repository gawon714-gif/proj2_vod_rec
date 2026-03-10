# Phase 2: VOD 임베딩 생성 및 저장

**상태**: 대기
**선행 조건**: Phase 1 완료 (vod_embedding 테이블, vod_collection 존재)

---

## 목표

RAG로 보강된 VOD 메타데이터를 텍스트로 변환하고
sentence-transformers로 384차원 벡터를 생성하여 Milvus에 저장한다.

---

## 입력 데이터 쿼리

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

---

## 임베딩 텍스트 구성

```python
def build_vod_text(row):
    parts = [f"[제목] {row['asset_nm']}"]
    if row['ct_cl'] or row['genre']:
        parts.append(f"[장르] {row['ct_cl']} / {row['genre']}")
    if row['director']:
        parts.append(f"[감독] {row['director']}")
    if row['smry']:
        parts.append(f"[줄거리] {row['smry']}")
    return "\n".join(parts)
```

---

## 처리 흐름

```
vod 테이블 조회
    → 텍스트 구성
    → sentence-transformers 모델로 벡터 변환 (배치 처리)
    → Milvus vod_collection에 저장
    → PostgreSQL vod_embedding에 메타데이터 저장
```

---

## 성능 설정

| 항목 | 값 |
|------|-----|
| 모델 | paraphrase-multilingual-MiniLM-L12-v2 (다국어 지원) |
| 배치 크기 | 256 |
| 예상 처리 속도 | 약 1,000건/분 |
| 예상 총 소요 시간 | 약 3시간 |

---

## 완료 기준

- [ ] VOD 166,159개 METADATA 임베딩 생성
- [ ] Milvus vod_collection 저장 완료
- [ ] vod_embedding 테이블 메타데이터 저장 완료
- [ ] 처리 레포트 저장
