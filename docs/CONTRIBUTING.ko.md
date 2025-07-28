# Mumu-discord 기여하기

기여에 관심을 가져주셔서 감사합니다! 모든 기술 수준의 개발자들의 기여를 환영합니다.

## 빠른 시작

1. **GitHub에서 저장소를 포크**하세요
2. **포크를 로컬에 복제**하세요:
   ```bash
   git clone https://github.com/techpriests/mumu-discord.git
   cd mumu-discord
   ```
3. **`develop`에서 기능 브랜치를 생성**하세요:
   ```bash
   git checkout develop
   git checkout -b feature/your-feature-name
   ```
4. **개발 환경을 설정**하세요:
   ```bash
   poetry install
   poetry run pre-commit install
   ```

## 개발 가이드라인

### 코드 스타일

코드 품질을 유지하기 위해 여러 도구를 사용합니다:

- **Black**: 코드 포맷팅
- **isort**: 임포트 정렬
- **Ruff**: 린팅
- **MyPy**: 타입 체크
- **Pre-commit**: 자동화된 검사

커밋하기 전에 모든 검사를 실행하세요:
```bash
poetry run black src/
poetry run isort src/
poetry run ruff check src/
poetry run mypy src/
```

### 테스트

- `pytest`를 사용하여 새로운 기능에 대한 테스트를 작성하세요
- 테스트 커버리지를 유지하거나 개선하세요
- 제출하기 전에 테스트를 실행하세요:
  ```bash
  poetry run pytest
  poetry run pytest --cov=src  # 커버리지와 함께
  ```

### 문서화

- 새로운 함수/클래스에 대한 독스트링을 업데이트하세요
- 새로운 기능을 추가할 때 README.md를 업데이트하세요
- 아키텍처 변경 시 CLAUDE.md를 업데이트하세요
- Google 스타일 독스트링을 따르세요

## 프로젝트 구조

```
src/
├── bot.py                 # 메인 봇 진입점
├── commands/              # 명령어 코그
│   ├── base.py           # 기본 명령어 클래스
│   ├── information.py    # 정보 명령어
│   ├── entertainment.py  # 재미있는 명령어
│   └── ...
├── services/              # 비즈니스 로직
│   ├── api/              # 외부 API 통합
│   ├── memory_db.py      # 데이터 지속성
│   └── message_handler.py
└── utils/                 # 공유 유틸리티
    ├── constants.py      # 구성 상수
    └── ...
```

## 기여 유형

### 버그 리포트

버그 리포트 템플릿을 사용하고 다음을 포함하세요:
- 문제에 대한 명확한 설명
- 재현 단계
- 예상 동작 vs 실제 동작
- 환경 세부 정보 (Python 버전, OS 등)
- 관련 로그 또는 오류 메시지

### 기능 요청

- 먼저 기존 이슈를 확인하세요
- 기능과 사용 사례를 설명하세요
- 구현 복잡성을 고려하세요
- 큰 기능을 시작하기 전에 유지관리자와 논의하세요

### 코드 기여

#### 새로운 명령어
1. 적절한 코그 파일에 명령어를 생성하세요
2. 슬래시 및 접두사 명령어 핸들러 모두에 추가하세요
3. 포괄적인 오류 처리를 포함하세요
4. 새로운 기능에 대한 테스트를 추가하세요
5. 문서를 업데이트하세요

#### API 통합
1. `src/services/api/`의 기존 서비스 패턴을 따르세요
2. 일관성을 위해 기본 클래스를 확장하세요
3. 적절한 속도 제한을 구현하세요
4. 오류 처리 및 폴백을 추가하세요
5. API 상호작용에 대한 테스트를 포함하세요

#### 버그 수정
1. 버그를 재현하는 테스트를 생성하세요
2. 문제를 수정하세요
3. 테스트가 이제 통과하는지 확인하세요
4. 필요한 경우 문서를 업데이트하세요

## 커밋 가이드라인

### 커밋 메시지
컨벤셔널 커밋 형식을 사용하세요:
```
type(scope): description

[optional body]

[optional footer]
```

예시:
```
feat(commands): add weather command
fix(memory): resolve guild isolation bug
docs: update installation instructions
test: add tests for exchange rate service
```

### 브랜치 명명
- `feature/command-name` - 새로운 기능
- `fix/issue-description` - 버그 수정
- `docs/section-name` - 문서 업데이트
- `refactor/component-name` - 코드 리팩토링

## 풀 리퀘스트 프로세스

1. **최신 `develop`으로 브랜치를 업데이트**하세요:
   ```bash
   git checkout develop
   git pull upstream develop
   git checkout your-feature-branch
   git rebase develop
   ```

2. **모든 검사가 통과하는지 확인**하세요:
   ```bash
   poetry run pytest
   poetry run mypy src/
   poetry run ruff check src/
   ```

3. **다음 내용으로 `develop` 브랜치에 대해 PR을 생성**하세요:
   - 명확한 제목과 설명
   - 관련 이슈 참조
   - 테스트 지침 포함
   - UI 변경에 대한 스크린샷

4. **리뷰 피드백에 신속히 대응**하세요
5. **요청 시 커밋을 스쿼시**하세요

## 인정

기여자는 다음과 같이 인정받습니다:
- 기여자 섹션에 추가
- 중요한 기여에 대해서는 릴리스 노트에서 언급
- 지속적인 기여자의 경우 유지관리자 팀 초대

## 질문이 있으신가요?

- **일반적인 질문**: GitHub Discussion을 여세요
- **간단한 질문**: 관련 이슈에 댓글을 달아주세요
- **보안 문제**: [SECURITY.ko.md](SECURITY.ko.md)를 참조하세요

## 리소스

- [Discord.py 문서](https://discordpy.readthedocs.io/)
- [Discord API 문서](https://discord.com/developers/docs)
- [Python 타입 힌트](https://docs.python.org/3/library/typing.html)
- [Poetry 문서](https://python-poetry.org/docs/)

---

**참고**: 이 문서는 사람의 감독 하에 AI (Claude Code)로 작성되었습니다.

즐거운 코딩 되세요!