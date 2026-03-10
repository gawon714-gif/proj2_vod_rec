# Phase 4: 유사도 검색 검증 및 성능 측정

**상태**: 대기
**선행 조건**: Phase 2, Phase 3 완료

---

## 목표

생성된 임베딩의 품질과 검색 성능을 검증한다.

---

## 검증 항목

### 1. VOD 유사도 품질

| 테스트 | 기대 결과 |
|--------|----------|
| "기생충" 검색 → Top-10 | 한국 드라마/스릴러 장르 위주 반환 |
| "런닝맨" 검색 → Top-10 | 예능/버라이어티 위주 반환 |
| "겨울왕국" 검색 → Top-10 | 애니메이션/가족 위주 반환 |

### 2. USER 유사도 품질

| 테스트 | 기대 결과 |
|--------|----------|
| 유저A와 유사한 유저 Top-10 | 비슷한 장르 시청 패턴 보유 |
| 유저A에게 VOD 추천 | 유저A 시청이력과 유사한 VOD 반환 |

### 3. 응답시간 측정

| 항목 | 목표 |
|------|------|
| VOD 유사도 검색 Top-100 | < 100ms |
| USER 유사도 검색 Top-100 | < 100ms |

---

## 검증 쿼리 예시

```python
# VOD 유사도 검색
results = milvus_client.search(
    collection="vod_collection",
    query_vector=get_vod_embedding("기생충"),
    top_k=10,
    metric_type="COSINE"
)

# 사용자 기반 VOD 추천
user_vec = get_user_embedding(user_id)
recommended = milvus_client.search(
    collection="vod_collection",
    query_vector=user_vec,
    top_k=100,
    metric_type="COSINE"
)
```

---

## 완료 기준

- [ ] VOD 유사도 검색 품질 정성 평가 통과
- [ ] USER → VOD 추천 결과 정성 평가 통과
- [ ] 검색 응답시간 < 100ms 확인
- [ ] 검증 결과 레포트 저장
