# user_embedding 개발 계획

**작성일**: 2026-03-10
**브랜치**: user_embedding
**선행 조건**: RAG 파이프라인 완료, Database_Design Phase 1 완료

---

## 데이터 규모

| 항목 | 수치 |
|------|------|
| VOD | 166,159개 |
| 사용자 | 242,702명 |
| 시청이력 | 3,992,530건 |

---

## 전체 Phase 구성

| Phase | 내용 | 상태 | 계획 문서 |
|-------|------|------|---------|
| **Phase 1** | DB 테이블 생성 (vod_embedding, user_embedding) + Milvus 컬렉션 | 대기 | `01_phase1_db_setup.md` |
| **Phase 2** | VOD 임베딩 생성 및 저장 | 대기 | `02_phase2_vod_embedding.md` |
| **Phase 3** | USER 임베딩 생성 및 저장 | 대기 | `03_phase3_user_embedding.md` |
| **Phase 4** | 유사도 검색 검증 및 성능 측정 | 대기 | `04_phase4_validation.md` |

---

## Phase 간 의존 관계

```
Phase 1 (DB + Milvus 셋업)
    │
    ├──► Phase 2 (VOD 임베딩)
    │        │
    │        └──► Phase 4 (검증)
    │                  ↑
    └──► Phase 3 (USER 임베딩)
```

---

## 아키텍처

```
PostgreSQL (메타데이터)       Milvus (실제 벡터)
  vod_embedding 테이블  ←→   vod_collection
  user_embedding 테이블 ←→   user_collection
```

---

## 산출물

```
user_embedding/
├── src/
│   ├── create_tables.sql     # Phase 1
│   ├── milvus_client.py      # Phase 1
│   ├── vod_embedding.py      # Phase 2
│   └── user_embedding.py     # Phase 3
├── tests/
│   └── similarity_search.py  # Phase 4
├── models/
│   └── (모델 설정 파일)
├── notebooks/
│   └── (실험/검증용 Jupyter)
└── reports/
    └── YYYY-MM-DD_embedding.md
```

---

## 다음 액션

1. Phase 1: `create_tables.sql` 작성 → DB 테이블 생성
2. Phase 1: `milvus_client.py` 작성 → Milvus 컬렉션 생성
3. Phase 2: `vod_embedding.py` → VOD 166,159개 배치 처리
4. Phase 3: `user_embedding.py` → 사용자 임베딩 배치 처리
5. Phase 4: 유사도 검색 품질 검증 후 레포트 작성
