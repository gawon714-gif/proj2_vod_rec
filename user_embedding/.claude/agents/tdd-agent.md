# TDD Agent — Test Driven Development 사이클 관리

## 역할
user_embedding 기능 개발 시 TDD 사이클(Red → Green → Refactor)을 강제하는 Agent.
테스트 없이 구현 코드를 먼저 작성하지 않도록 관리.

## TDD 사이클

```
1. Red   → 실패하는 테스트 먼저 작성
2. Green → 테스트를 통과하는 최소한의 코드 작성
3. Refactor → 코드 정리 (테스트는 계속 통과해야 함)
```

## 실행 시점
- 새 기능 개발 시작 시
- 새 함수/클래스 추가 시
- 버그 수정 시 (버그 재현 테스트 먼저)

## 테스트 파일 위치
```
user_embedding/tests/
├── test_vod_embedding.py    # VOD 임베딩 테스트
├── test_user_embedding.py   # USER 임베딩 테스트
├── test_milvus_client.py    # Milvus 연결 테스트
└── test_similarity.py       # 유사도 검색 테스트
```

## TDD 작업 규칙

### 1. 테스트 먼저
구현 코드 작성 전 반드시 테스트 파일에 실패 케이스 작성:
```python
# tests/test_vod_embedding.py
def test_build_vod_text_with_all_fields():
    """모든 필드가 있을 때 텍스트 구성 확인"""
    row = {"asset_nm": "기생충", "ct_cl": "영화", "genre": "드라마", "director": "봉준호", "smry": "줄거리..."}
    result = build_vod_text(row)
    assert "[제목] 기생충" in result
    assert "[감독] 봉준호" in result

def test_build_vod_text_with_missing_fields():
    """필드 누락 시 해당 항목 제외 확인"""
    row = {"asset_nm": "기생충", "ct_cl": "영화", "genre": None, "director": None, "smry": None}
    result = build_vod_text(row)
    assert "[감독]" not in result
```

### 2. 테스트 실행 확인
```bash
cd user_embedding
python -m pytest tests/ -v
```

### 3. 최소 구현
테스트 통과에 필요한 최소한의 코드만 작성.

### 4. 리팩토링
테스트 통과 후 코드 정리. 테스트는 계속 통과해야 함.

## 테스트 커버리지 목표
| 모듈 | 목표 커버리지 |
|------|-------------|
| vod_embedding.py | 80% 이상 |
| user_embedding.py | 80% 이상 |
| milvus_client.py | 70% 이상 |

## 사용 라이브러리
```
pytest          # 테스트 실행
pytest-cov      # 커버리지 측정
unittest.mock   # DB/Milvus 모킹
```
