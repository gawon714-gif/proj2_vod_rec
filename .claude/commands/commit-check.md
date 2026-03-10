커밋 전 보안 점검을 아래 순서로 실행해줘.

## 1단계 — 스테이징된 파일 확인
```bash
git diff --cached --name-only
```

## 2단계 — 민감 파일 포함 여부 점검
스테이징된 파일 목록에서 아래 패턴이 있으면 즉시 경고:
- `.env`, `*.env`, `config/*.env`
- `*secret*`, `*password*`, `*credential*`, `*.key`

## 3단계 — 코드 내 하드코딩 점검
스테이징된 `.py` 파일에서 아래 패턴 검색:
```bash
git diff --cached | grep -iE "(password|api_key|secret)\s*=\s*['\"][^'\"]{4,}"
```
발견 시 해당 줄과 파일명 출력.

## 4단계 — .gitignore 필수 항목 확인
`.gitignore`에 아래 항목이 모두 있는지 확인:
- `.env`
- `*.env`
- `config/*.env`
- `*.key`
- `__pycache__/`
- `*.pyc`

## 결과 출력 형식
```
=== 커밋 전 보안 점검 ===
✅ 민감 파일 없음
✅ 하드코딩된 키 없음
✅ .gitignore 정상
→ 커밋해도 안전합니다.

또는

❌ 위험: config/.env 가 스테이징되어 있습니다. git restore --staged 로 제거하세요.
⚠️  경고: search_tmdb.py 12번째 줄에 api_key 하드코딩 의심
```
