# Phase 3: USER 임베딩 생성 및 저장

**상태**: 대기
**선행 조건**: Phase 1 완료 (user_embedding 테이블, user_collection 존재)

---

## 목표

사용자 시청이력 + 인구통계 데이터를 기반으로
448차원 HYBRID 벡터를 생성하여 Milvus에 저장한다.

---

## 임베딩 구성 (HYBRID = 256 + 128 + 64)

| 타입 | 차원 | 입력 |
|------|------|------|
| BEHAVIOR | 256 | 장르별 시청횟수, 완료율, 만족도 |
| GENRE_PREF | 128 | 장르별 친화도 점수 |
| DEMOGRAPHIC | 64 | 연령대, 재택률, 구독정보 등 |
| **HYBRID** | **448** | 위 3개 결합 |

---

## 입력 데이터 쿼리

```sql
-- 시청이력 기반 (BEHAVIOR + GENRE_PREF)
SELECT
    wh.user_id_fk,
    v.genre,
    COUNT(*)                AS watch_count,
    AVG(wh.completion_rate) AS avg_completion,
    AVG(wh.satisfaction)    AS avg_satisfaction
FROM watch_history wh
JOIN vod v ON wh.vod_id_fk = v.full_asset_id
GROUP BY wh.user_id_fk, v.genre
ORDER BY wh.user_id_fk, watch_count DESC;

-- 인구통계 기반 (DEMOGRAPHIC)
SELECT
    sha2_hash,
    age_grp10,
    inhome_rate,
    svod_scrb_cnt_grp,
    paid_chnl_cnt_grp,
    kids_use_pv_month1,
    nfx_use_yn
FROM users;
```

---

## 처리 흐름

```
watch_history + users 테이블 조회
    → 사용자별 장르 시청 통계 집계
    → BEHAVIOR 벡터 생성 (256차원)
    → GENRE_PREF 벡터 생성 (128차원)
    → DEMOGRAPHIC 벡터 생성 (64차원)
    → HYBRID 결합 (448차원)
    → Milvus user_collection에 저장
    → PostgreSQL user_embedding에 메타데이터 저장
```

---

## 콜드스타트 처리

시청이력이 없는 신규 사용자:
- 인구통계(DEMOGRAPHIC) 기반으로만 임베딩 생성
- 동일 연령대 인기 VOD 추천으로 대체

---

## 완료 기준

- [ ] 활성 사용자 HYBRID 임베딩 생성
- [ ] Milvus user_collection 저장 완료
- [ ] user_embedding 테이블 메타데이터 저장 완료
- [ ] 콜드스타트 사용자 처리 확인
- [ ] 처리 레포트 저장
