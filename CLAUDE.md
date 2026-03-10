# VOD 추천 시스템 — 공통 작업 지침

모든 브랜치에서 공통으로 적용되는 규칙.

---

## 프로젝트 구조

```
vod_recommendation/
├── CLAUDE.md                  # 공통 규칙 (이 파일)
├── .claude/
│   └── agents/
│       ├── secret-agent.md    # 보안 점검 Agent
│       └── report-agent.md    # 레포트 작성 Agent
├── RAG/                       # RAG 파이프라인 브랜치
│   ├── src/                   # 소스 코드
│   ├── config/                # 설정 파일 (.env 등)
│   ├── reports/               # 작업 레포트 저장
│   └── .claude/claude.md      # RAG 브랜치 전용 지침
├── Database_Design/           # DB 설계 브랜치
└── README.md
```

---

## 보안 규칙 (필수)

- `.env` 파일은 절대 Read 툴로 열지 말 것
- API 키, 비밀번호가 포함된 파일을 커밋하지 말 것
- 민감 정보가 의심되는 파일은 작업 전 사용자에게 확인
- `.gitignore`에 반드시 포함: `.env`, `*.key`, `config/*.env`
- 커밋 전 항상 `git diff`로 민감 정보 노출 여부 확인

---

## Agent 사용 규칙

### 레포트 작성
- 주요 작업 완료 후 `report-agent`를 활용해 레포트 작성
- 저장 위치: `{브랜치명}/reports/YYYY-MM-DD_{작업명}.md`
- 레포트에는 반드시 포함: 작업 내용, 결과, 사용 도구, 다음 단계

### 보안 점검
- 커밋 전 `secret-agent`로 민감 정보 노출 여부 점검
- 새 API 키 추가 시 반드시 `.env`에만 저장, 코드에 하드코딩 금지

---

## 커밋 규칙

```
feat:    새 기능 추가
fix:     버그 수정
refactor: 코드 개선
chore:   설정/환경 변경
docs:    문서 작성
```

- 커밋 메시지는 한국어 또는 영어 통일
- 사용자가 명시적으로 요청할 때만 커밋
- 민감 파일(.env 등) 절대 커밋 금지

---

## 브랜치 전략

| 브랜치 | 역할 |
|--------|------|
| `main` | 안정 버전, PR로만 병합 |
| `RAG` | RAG 파이프라인 개발 |
| `Database_Design` | DB 스키마 설계 |

- 작업은 각 브랜치에서 진행 후 main으로 PR
- 공통 규칙 변경 시 main에서 각 브랜치로 merge

---

## DB 연결

- host: localhost, port: 5432
- dbname: vod_recommendation
- 접속 정보는 `.env`에서만 관리
- 테이블: `vod` (메인), `users`, `watch_history`
