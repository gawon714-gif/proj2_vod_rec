# Phase 4: 추천 캐시 테이블 + Re-Ranking

**상태**: 대기 (Phase 3 완료 후 시작)
**선행 조건**: VOD_EMBEDDING, USER_EMBEDDING 생성 완료, Milvus 검색 가능 상태
**목표**: 사용자별 추천 결과를 PostgreSQL에 캐싱하여 10,000 QPS 처리

---

## 목표

1. Milvus 벡터 검색 결과를 PostgreSQL VOD_RECOMMENDATION 테이블에 캐싱
2. Re-Ranking 로직 적용 (신선도, 인기도, 다양성, 비즈니스 로직)
3. TTL(7일) 기반 캐시 관리
4. 콜드스타트 처리 (신규 사용자 / 신규 VOD)

---

## DDL - VOD_RECOMMENDATION 테이블

```sql
CREATE TABLE vod_recommendation (
    recommendation_id   BIGINT      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 참조
    user_id_fk          VARCHAR(64)     NOT NULL,
    vod_id_fk           VARCHAR(64)     NOT NULL,

    -- 순위 정보
    rank_initial        INTEGER         NOT NULL,   -- Milvus 1차 검색 순위 (1~1000)
    rank_final          INTEGER         NOT NULL,   -- Re-Ranking 후 최종 순위

    -- 점수
    similarity_score    REAL            NOT NULL CHECK (similarity_score >= 0 AND similarity_score <= 1),
    rerank_score        REAL            NOT NULL CHECK (rerank_score >= 0 AND rerank_score <= 1),

    -- Re-Ranking 상세 요인 (JSON)
    rerank_factors      JSONB,
    --  예시:
    --  {
    --    "freshness":            0.8,   -- 신규 VOD 가산점 (출시 30일 이내)
    --    "popularity":           0.6,   -- 시청 횟수 기반 인기도
    --    "user_pref_match":      0.9,   -- 사용자 장르 선호도 일치율
    --    "diversity_penalty":   -0.1,   -- 동일 장르 반복 패널티
    --    "cold_start_boost":     0.0    -- 신규 VOD 부스트
    --  }

    -- 추천 이유 (UI 표시용)
    reason              VARCHAR(255),   -- "유사 장르 추천", "인기 상승 작품" 등

    -- 캐시 TTL
    created_at          TIMESTAMP WITH TIME ZONE    NOT NULL DEFAULT NOW(),
    expired_at          TIMESTAMP WITH TIME ZONE,   -- 기본 7일 후

    -- 피드백 (재학습용)
    is_clicked          BOOLEAN         NOT NULL DEFAULT FALSE,
    is_watched          BOOLEAN         NOT NULL DEFAULT FALSE,
    click_timestamp     TIMESTAMP WITH TIME ZONE,

    CONSTRAINT fk_rec_user
        FOREIGN KEY (user_id_fk) REFERENCES users(sha2_hash) ON DELETE CASCADE,
    CONSTRAINT fk_rec_vod
        FOREIGN KEY (vod_id_fk)  REFERENCES vod(full_asset_id) ON DELETE CASCADE,
    CONSTRAINT uq_recommendation
        UNIQUE (user_id_fk, vod_id_fk, created_at)
);

-- 인덱스
CREATE INDEX idx_rec_user_rank  ON vod_recommendation (user_id_fk, rank_final)
    WHERE expired_at > NOW();          -- 유효한 추천만 인덱싱 (부분 인덱스)

CREATE INDEX idx_rec_expired    ON vod_recommendation (expired_at);
CREATE INDEX idx_rec_rerank     ON vod_recommendation (rerank_score DESC);
CREATE INDEX idx_rec_created    ON vod_recommendation (created_at);

COMMENT ON TABLE vod_recommendation IS '사용자별 추천 캐시. TTL 7일. Re-Ranking 결과 저장.';
COMMENT ON COLUMN vod_recommendation.rerank_factors IS 'Re-Ranking 각 요인의 점수. JSONB로 유연한 확장.';
```

---

## 핵심 쿼리

### 사용자 추천 조회 (API 엔드포인트)

```sql
-- Top-50 추천 VOD 조회 (캐시 히트)
SELECT
    r.rank_final,
    v.full_asset_id,
    v.asset_nm,
    v.ct_cl,
    v.genre,
    v.disp_rtm_sec,
    r.similarity_score,
    r.rerank_score,
    r.reason
FROM vod_recommendation r
JOIN vod v ON r.vod_id_fk = v.full_asset_id
WHERE r.user_id_fk = :user_id
  AND r.expired_at > NOW()
  AND r.is_clicked = FALSE
ORDER BY r.rank_final
LIMIT 50;
```

### 캐시 만료 관리 (배치 - 매일 새벽)

```sql
-- 만료된 비클릭 추천 삭제
DELETE FROM vod_recommendation
WHERE expired_at < NOW()
  AND is_clicked = FALSE;

-- 클릭된 추천은 피드백 데이터로 보관 (30일)
DELETE FROM vod_recommendation
WHERE expired_at < NOW() - INTERVAL '30 days'
  AND is_clicked = TRUE;
```

### Re-Ranking 결과 저장 (Python에서 호출)

```sql
INSERT INTO vod_recommendation
    (user_id_fk, vod_id_fk, rank_initial, rank_final,
     similarity_score, rerank_score, rerank_factors, reason, expired_at)
VALUES
    (:user_id, :vod_id, :rank_initial, :rank_final,
     :sim_score, :rerank_score, :rerank_factors::jsonb, :reason,
     NOW() + INTERVAL '7 days')
ON CONFLICT (user_id_fk, vod_id_fk, created_at) DO NOTHING;
```

---

## Re-Ranking 로직

```
최종 점수 = similarity_score
          + freshness_boost
          + popularity_score × 0.2
          + user_pref_match × 0.3
          - diversity_penalty
          + cold_start_boost
```

### 신규 VOD 부스트 (콜드스타트)

```sql
SELECT
    full_asset_id,
    CASE
        WHEN created_at > NOW() - INTERVAL '7 days'  THEN 0.8
        WHEN created_at > NOW() - INTERVAL '30 days' THEN 0.5
        ELSE 0.0
    END AS freshness_boost
FROM vod
WHERE is_active = TRUE;   -- (Phase 5에서 is_active 컬럼 추가 시)
```

### 신규 사용자 처리 (콜드스타트)

```sql
-- 동일 연령대의 인기 VOD 조회 (watch_history 0건 사용자)
SELECT
    v.full_asset_id,
    v.asset_nm,
    v.genre,
    COUNT(wh.watch_history_id)  AS view_count,
    AVG(wh.satisfaction)        AS avg_satisfaction
FROM vod v
JOIN watch_history wh ON v.full_asset_id = wh.vod_id_fk
JOIN users u ON wh.user_id_fk = u.sha2_hash
WHERE u.age_grp10 = :target_age_grp
  AND wh.satisfaction > 0.6
GROUP BY v.full_asset_id, v.asset_nm, v.genre
HAVING COUNT(*) >= 10
ORDER BY avg_satisfaction DESC, view_count DESC
LIMIT 100;
```

---

## 완료 기준

- [ ] `vod_recommendation` 테이블 생성 완료
- [ ] Re-Ranking 파이프라인 구현 및 테스트
- [ ] 사용자별 추천 결과 캐싱 (Top-100 저장)
- [ ] 추천 조회 응답시간 < 50ms (인덱스 캐시 히트 기준)
- [ ] TTL 만료 배치 작동 확인
- [ ] 콜드스타트 사용자/VOD 처리 검증
- [ ] 피드백 루프 (is_clicked 업데이트) 동작 확인
