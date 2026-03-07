# Phase 5: 성능 최적화 + 프로덕션 배포

**상태**: 대기 (Phase 4 완료 후 시작)
**선행 조건**: 전체 시스템 구성 완료 (Phase 1~4)
**목표**: 10,000 QPS 처리, 주요 쿼리 100ms 이하

---

## 성능 목표

| 쿼리 패턴 | 목표 응답시간 | 담당 인덱스 |
|-----------|------------|----------|
| 사용자별 추천 조회 | < 50ms | `idx_rec_user_rank` (부분 인덱스) |
| 사용자별 시청이력 조회 | < 100ms | `idx_wh_user_id` |
| VOD별 시청 통계 | < 100ms | `idx_wh_vod_id` |
| 날짜 범위 조회 | < 500ms | `idx_wh_strt_dt` + 파티션 프루닝 |
| VOD 제목 검색 | < 50ms | `idx_vod_asset_nm_trgm` (GIN) |
| 만족도 상위 VOD | < 200ms | `idx_wh_satisfaction DESC` |

---

## 1. 파티셔닝 확장 계획

### WATCH_HISTORY - 연도 파티션 추가

현재 구성: 2023, 2024, 2025, default 파티션

```sql
-- 2026년 데이터 증가 대비 파티션 사전 생성
CREATE TABLE watch_history_2026
    PARTITION OF watch_history
    FOR VALUES FROM ('2026-01-01 00:00:00+00') TO ('2027-01-01 00:00:00+00');

-- 월별 서브파티셔닝 (데이터 100M건 초과 시 고려)
-- watch_history_2025를 월별로 분할:
CREATE TABLE watch_history_2025_q1
    PARTITION OF watch_history_2025
    FOR VALUES FROM ('2025-01-01') TO ('2025-04-01');
```

### VOD_RECOMMENDATION - 해시 파티셔닝 (선택)

```sql
-- 사용자 수 급증 시 해시 파티셔닝 적용
-- 현재는 단일 테이블 유지, 사용자 100만 초과 시 검토
ALTER TABLE vod_recommendation
    PARTITION BY HASH (user_id_fk) PARTITIONS 64;
```

---

## 2. 캐싱 레이어 설계

### 2단계 캐싱 아키텍처

```
클라이언트 요청
    │
    ▼
[Redis L1 캐시] TTL: 1시간
    - 활성 사용자 Top-1,000명의 추천 결과
    - 키: "rec:{user_id}", 값: JSON Top-50
    │ 미스 시
    ▼
[PostgreSQL L2 캐시] TTL: 7일
    - vod_recommendation 테이블
    - 전체 사용자 추천 결과
    │ 미스 시
    ▼
[Milvus 실시간 검색]
    - 벡터 유사도 검색 + Re-Ranking
    - 결과 → PostgreSQL 저장 → Redis 저장
```

### Redis 키 설계

```
rec:{user_id}           → 사용자 추천 리스트 (JSON)
vod:meta:{full_asset_id} → VOD 메타데이터 캐시 (Hash)
trending:genre:{genre}  → 장르별 인기 VOD (Sorted Set)
cold:age:{age_grp10}    → 연령대별 기본 추천 (JSON)
```

---

## 3. PostgreSQL 설정 튜닝

```sql
-- postgresql.conf 권장 설정 (16GB RAM 기준)
-- shared_buffers = 4GB             (RAM의 25%)
-- effective_cache_size = 12GB      (RAM의 75%)
-- work_mem = 64MB                  (복잡한 정렬/해시 조인)
-- maintenance_work_mem = 1GB       (VACUUM, CREATE INDEX)
-- max_connections = 200            (connection pool 활용)
-- wal_compression = on             (WAL 압축)
-- checkpoint_completion_target = 0.9

-- 현재 설정 확인
SHOW shared_buffers;
SHOW work_mem;
SHOW effective_cache_size;
```

### 연결 풀링 (PgBouncer 권장)

```
애플리케이션 (최대 1,000 연결)
    │
    ▼
PgBouncer (transaction mode)
    │
    ▼
PostgreSQL (max_connections = 200)
```

---

## 4. VACUUM 및 ANALYZE 정책

```sql
-- 수동 ANALYZE (대규모 데이터 로드 후)
ANALYZE vod;
ANALYZE users;
ANALYZE watch_history;
ANALYZE vod_recommendation;

-- autovacuum 설정 (watch_history처럼 삽입이 많은 테이블)
ALTER TABLE watch_history SET (
    autovacuum_analyze_scale_factor = 0.01,  -- 1% 변경 시 ANALYZE
    autovacuum_vacuum_scale_factor = 0.02    -- 2% 변경 시 VACUUM
);
```

---

## 5. 성능 테스트 쿼리

```sql
-- 1. 사용자별 시청이력 조회 성능 테스트
EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
SELECT wh.*, v.asset_nm, v.genre
FROM watch_history wh
JOIN vod v ON wh.vod_id_fk = v.full_asset_id
WHERE wh.user_id_fk = '0000f3514448d06cddfb916d39bcee86560093ee1d3ea475c8c33b3dac8a18e4'
ORDER BY wh.strt_dt DESC
LIMIT 20;
-- 기대: Index Scan on idx_wh_user_id, < 100ms

-- 2. VOD별 시청 통계
EXPLAIN (ANALYZE, BUFFERS)
SELECT
    vod_id_fk,
    COUNT(*)            AS view_count,
    AVG(completion_rate) AS avg_completion,
    AVG(satisfaction)    AS avg_satisfaction
FROM watch_history
WHERE vod_id_fk = 'cjc|M4996864LFOL10619201'
GROUP BY vod_id_fk;
-- 기대: < 100ms

-- 3. 날짜 범위 조회 (파티션 프루닝 확인)
EXPLAIN (ANALYZE, BUFFERS)
SELECT COUNT(*), AVG(satisfaction)
FROM watch_history
WHERE strt_dt BETWEEN '2025-01-01' AND '2025-01-31';
-- 기대: Partition pruning 적용 (watch_history_2025만 스캔), < 500ms

-- 4. 만족도 상위 VOD 조회
EXPLAIN (ANALYZE, BUFFERS)
SELECT vod_id_fk, AVG(satisfaction) AS avg_sat, COUNT(*) AS cnt
FROM watch_history
WHERE satisfaction > 0.7
GROUP BY vod_id_fk
ORDER BY avg_sat DESC
LIMIT 100;
-- 기대: < 200ms

-- 5. 추천 캐시 조회 (Phase 4 완료 후)
EXPLAIN (ANALYZE, BUFFERS)
SELECT r.rank_final, v.asset_nm, v.genre, r.rerank_score
FROM vod_recommendation r
JOIN vod v ON r.vod_id_fk = v.full_asset_id
WHERE r.user_id_fk = :user_id
  AND r.expired_at > NOW()
ORDER BY r.rank_final
LIMIT 50;
-- 기대: < 50ms
```

---

## 6. 모니터링 쿼리

```sql
-- 일일 활성 사용자 및 시청 통계
SELECT
    DATE(strt_dt)                       AS watch_date,
    COUNT(DISTINCT user_id_fk)          AS dau,
    COUNT(*)                            AS total_sessions,
    ROUND(AVG(completion_rate)::numeric, 4) AS avg_completion,
    ROUND(AVG(satisfaction)::numeric, 4)    AS avg_satisfaction
FROM watch_history
WHERE strt_dt >= NOW() - INTERVAL '30 days'
GROUP BY DATE(strt_dt)
ORDER BY watch_date DESC;

-- 느린 쿼리 확인 (pg_stat_statements 활성화 필요)
SELECT
    query,
    calls,
    ROUND((total_exec_time / calls)::numeric, 2) AS avg_ms,
    ROUND(total_exec_time::numeric, 2) AS total_ms
FROM pg_stat_statements
ORDER BY avg_ms DESC
LIMIT 20;

-- 테이블 크기 모니터링
SELECT
    relname AS table_name,
    pg_size_pretty(pg_total_relation_size(oid)) AS total_size,
    pg_size_pretty(pg_relation_size(oid)) AS data_size
FROM pg_class
WHERE relname IN ('vod','users','watch_history','vod_recommendation',
                  'vod_embedding','user_embedding')
ORDER BY pg_total_relation_size(oid) DESC;
```

---

## 7. 프로덕션 체크리스트

### 배포 전
- [ ] `create_tables.sql` 스테이징 환경에서 검증 완료
- [ ] `migrate.py` 전체 CSV 데이터 로드 완료 (166K VOD / 242K 사용자 / 4M 시청이력)
- [ ] 행 수 검증 완료 (vod: 166,159 / users: 242,702 / watch_history: 3,992,530)
- [ ] `pg_stat_statements` 확장 활성화
- [ ] PgBouncer 연결 풀 설정
- [ ] Redis 캐시 서버 설정
- [ ] Milvus 서버 설정 및 컬렉션 생성

### 배포 후
- [ ] 쿼리 응답시간 목표치 달성 확인 (EXPLAIN ANALYZE 결과)
- [ ] autovacuum 동작 확인
- [ ] 모니터링 대시보드 설정 (Grafana + pg_stat_statements)
- [ ] 알림 설정 (느린 쿼리 > 1초, DB 용량 > 80%)

---

## 예상 DB 크기 (Phase 1~4 완료 기준)

| 테이블 | 예상 크기 |
|--------|---------|
| vod | 5~10MB |
| users | 20~30MB |
| watch_history | 150~200MB |
| vod_recommendation | 50~100MB |
| vod_embedding (메타만) | 20~30MB |
| user_embedding (메타만) | 20~30MB |
| **합계** | **~400MB** |
