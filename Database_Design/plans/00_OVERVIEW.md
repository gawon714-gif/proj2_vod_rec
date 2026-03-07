# VOD 추천 시스템 - Database Design 전체 계획

**작성일**: 2026-03-07
**프로젝트**: VOD 추천 웹서비스 - PostgreSQL 데이터베이스
**대상 DB**: PostgreSQL 15+
**브랜치**: Database_Design

---

## 데이터 규모 (실측치 기준)

| 항목 | 수치 |
|------|------|
| 시청 이력 | 3,992,530건 |
| 고유 사용자 | 242,702명 |
| 고유 VOD | 166,159개 |
| 수집 기간 | 2023-01-01 ~ 2023-01-31 |
| 평균 시청 완료율 | 46.76% |
| 평균 만족도 | 0.443 |

---

## 전체 Phase 구성

| Phase | 내용 | 상태 | 계획 문서 |
|-------|------|------|---------|
| **Phase 1** | 기본 스키마 (VOD, USERS, WATCH_HISTORY) | **완료** | `01_phase1_basic_schema.md` |
| **Phase 2** | RAG 파이프라인 - NULL 컬럼 보강 | 대기 | `02_phase2_rag_pipeline.md` |
| **Phase 3** | 벡터 임베딩 (pgvector + Milvus) | 대기 | `03_phase3_vector_embedding.md` |
| **Phase 4** | 추천 캐시 테이블 + Re-Ranking | 대기 | `04_phase4_recommendation.md` |
| **Phase 5** | 성능 최적화 + 프로덕션 배포 | 대기 | `05_phase5_performance.md` |

---

## Phase 간 의존 관계

```
Phase 1 (기본 스키마)
    │
    ├──► Phase 2 (RAG 파이프라인)
    │        │
    │        └──► Phase 3 (벡터 임베딩)
    │                  │
    │                  └──► Phase 4 (추천 캐시)
    │                            │
    └──────────────────────────► Phase 5 (성능 최적화)
```

- Phase 2는 Phase 1 완료 후 독립적으로 진행 가능
- Phase 3은 Phase 2의 director/smry 보강 데이터를 임베딩 입력으로 활용
- Phase 4는 Phase 3의 벡터 인덱스가 존재해야 추천 생성 가능
- Phase 5는 전체 시스템 구성 완료 후 최적화

---

## 산출물 현황

```
Database_Design/
├── schema/
│   ├── create_tables.sql    [완료] VOD, USERS, WATCH_HISTORY DDL
│   └── DESIGN.md            [완료] 설계 문서
├── migration/
│   └── migrate.py           [완료] CSV → PostgreSQL 마이그레이션
└── plans/
    ├── 00_OVERVIEW.md       [현재 문서]
    ├── 01_phase1_basic_schema.md
    ├── 02_phase2_rag_pipeline.md
    ├── 03_phase3_vector_embedding.md
    ├── 04_phase4_recommendation.md
    └── 05_phase5_performance.md
```

---

## 다음 액션

1. **즉시 실행 가능**: migrate.py 실행 → CSV 데이터를 PostgreSQL에 로드
2. **병행 가능**: Phase 2 RAG 파이프라인 (RAG 브랜치와 협업)
3. **이후**: Phase 3 벡터 임베딩 설계 시작
