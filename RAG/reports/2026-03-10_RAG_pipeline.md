# RAG 파이프라인 작업 레포트

- **작업 기간**: 2026-03-09 ~ 2026-03-10
- **브랜치**: RAG
- **목적**: VOD 메타데이터 결측치를 외부 API로 자동 채우기

---

## 1. 작업 개요

VOD 166,159건 중 결측치가 있는 항목을 TMDB, KMDB API로 검색하여 자동으로 채움.
기존 컬럼(director, cast_lead, cast_guest, rating, release_date) 외 신규 컬럼(smry, genre, asset_prod, series_nm) 추가 처리.

---

## 2. 사용 도구 및 API

| API | 용도 | 비용 |
|-----|------|------|
| TMDB (themoviedb.org) | 영화/TV 메타데이터 | 무료 |
| KMDB (koreafilm.or.kr) | 한국 콘텐츠 메타데이터 | 무료 (공공데이터) |
| Rule-based | 키즈 콘텐츠 rating 자동 적용 | - |
| Ollama (llama3.2:3b) | 초기 시도 → 할루시네이션으로 제거 | 로컬 |

**라이브러리**: psycopg2, requests, python-dotenv, concurrent.futures

---

## 3. 처리 결과

### 전체 처리 현황

| 항목 | 건수 | 비율 |
|------|-----:|-----:|
| 전체 VOD | 166,159 | 100% |
| 처리 완료 | 165,947 | 99.9% |
| 미처리 | 212 | 0.1% |

### 소스별 결과

| 소스 | 건수 | 비율 |
|------|-----:|-----:|
| TMDB | 75,735 | 45.6% |
| not_found | 72,120 | 43.4% |
| rule_based | 18,080 | 10.9% |

### 컬럼별 채움 결과

| 컬럼 | RAG 전 | RAG 후 채움률 |
|------|--------|-------------:|
| smry | 0% (신규) | 99.8% |
| genre | 0% (신규) | 99.8% |
| series_nm | 0% (신규) | 88.8% |
| director | ~10% | 90.3% |
| release_date | ~55% | 45.7% |
| cast_lead | ~45% | 45.1% |
| cast_guest | ~41% | 40.8% |
| rating | ~24% | 24.3% |
| asset_prod | 0% (신규) | 14.7% |

---

## 4. 처리 방식

### 검색 우선순위
```
한국 콘텐츠 → KMDB 먼저 → 실패 시 TMDB(tv)
해외 콘텐츠 → TMDB(movie)
키즈 → rule_based (rating=전체이용가 자동 적용)
전부 실패 → not_found 마킹
```

### 제목 정규화
API 검색 전 회차 정보 제거:
```python
EPISODE_PATTERN = re.compile(
    r'\s*((시즌\s*\d+|[Ss]eason\s*\d+|[A-Za-z]+)\s+)?'
    r'\d+\s*(회|화|강|편|부)?'
    r'[\.\s]*$', re.IGNORECASE
)
# 런닝맨 635회 → 런닝맨
# 가면라이더 빌드 12회. → 가면라이더 빌드
```

### 성능 최적화
| 기법 | 내용 |
|------|------|
| 병렬 처리 | ThreadPoolExecutor(max_workers=20) |
| DB 커넥션 풀 | ThreadedConnectionPool(maxconn=40) |
| 시리즈 캐싱 | 동일 시리즈 API 1회만 호출 |
| 타임아웃 | 3초 초과 시 다음 진행 |

### DB 저장 방식
```sql
-- 추적 컬럼
rag_processed    BOOLEAN    -- 처리 완료 여부
rag_source       VARCHAR    -- TMDB / KMDB / rule_based / not_found
rag_processed_at TIMESTAMP  -- 처리 시각

-- 배열은 JSON으로 저장
cast_lead = '["송강호","이선균","최우식"]'
```

---

## 5. 데이터 정제 내역

| 작업 | 건수 | 내용 |
|------|-----:|------|
| rating 정규화 | 36,933 | `15`, `All`, `19+` → 한국어 표준 표기 |
| asset_prod 정제 | 141,673 | RVOD/SVOD/FOD(서비스 유형) → NULL |
| genre 정규화 | 58,561 | 영문/중복 표기 → 한국어 통일 |
| series_nm 오매칭 | 18,317 | 판매관명/장르명 → NULL |
| 영화 series_nm | 17,979 | 영화에 시리즈명 불필요 → NULL |
| director 쉼표 | 220 | 다중 감독 → 첫 번째만 |
| smry 이상치 | 258 | 10자 미만 / 미래날짜 / 영문 → NULL |
| 이용안내 콘텐츠 | 12 | CJ헬로 서비스 가이드 → DB 삭제 |
| cast JSON 오류 | 25 | `"null"` / 형식 오류 → NULL 또는 수정 |

---

## 6. 롤백 이력

| 시점 | 대상 | 원인 | 조치 |
|------|-----:|------|------|
| 1차 | 431건 | Ollama 할루시네이션 | 전량 롤백 후 TMDB 재처리 |
| 2차 | ~18,000건 | KMDB 키 없이 처리된 한국 콘텐츠 | retry_kmdb.py로 재처리 |
| 3차 | 23,825건 | 제목 정규화 미흡 (마침표/화/강) | EPISODE_PATTERN 개선 후 재처리 → 16,145건 추가 성공 |

---

## 7. not_found 72,120건 분석

| ct_cl | 건수 | 원인 |
|-------|-----:|------|
| TV애니메이션 | 21,956 | 유튜버 채널, 구작 애니 → API 미등록 |
| TV 연예/오락 | 17,455 | 방송사 단독 예능 |
| TV드라마 | 12,508 | 오래된 국내 드라마, 지역 방송 |
| 영화 | 6,731 | 저예산·독립영화 |
| TV 시사/교양 | 5,819 | 다큐·교양 TMDB 등록률 낮음 |

---

## 8. 처리 못한 항목 향후 보완 방법

| 대상 | API | 특징 |
|------|-----|------|
| 일본 애니 | Jikan (MyAnimeList) | 무료, 키 불필요 |
| 한국 드라마/예능 | 네이버 검색 API | 국내 콘텐츠 강점 |
| 한국 영화 | KOBIS (영화진흥위원회) | 공공데이터포털 신청 |
| 교육 콘텐츠 | EBS Open API | openapi.ebs.co.kr |
| 유튜버 채널 | 없음 | 공식 DB 존재하지 않음 |

---

## 9. 성능

| 항목 | 수치 |
|------|------|
| 처리 속도 | 약 250건/분 |
| 총 소요 시간 | 약 10~11시간 (재처리 포함) |
| 채움률 (smry/genre) | 99.8% |
| 채움률 (director) | 90.3% |
| 채움률 (cast/rating) | 24~45% |

---

## 10. 다음 단계

1. 네이버 검색 API 연동 → not_found 한국 콘텐츠 보완
2. Jikan API 연동 → TV애니메이션 보완
3. KOBIS API 연동 → 한국 영화 보완
4. **추천 모델 개발 시작** (ALS / Surprise 라이브러리)
5. 추천 API 서버 구축
