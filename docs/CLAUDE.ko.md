# CLAUDE.ko.md

이 파일은 이 저장소의 코드 작업 시 Claude Code (claude.ai/code)에게 가이드를 제공합니다.

## 개발 명령어

### 핵심 명령어
- **의존성 설치**: `poetry install`
- **테스트 실행**: `poetry run pytest`
- **타입 체크**: `poetry run mypy src/`
- **린팅**: `poetry run ruff check src/`
- **코드 포맷팅**: `poetry run black src/`
- **임포트 정렬**: `poetry run isort src/`

### Docker 개발
- **봇 빌드 및 실행**: `docker-compose up -d`
- **로그 보기**: `docker-compose logs -f bot`
- **봇 중지**: `docker-compose down`

### 테스트
- **특정 테스트 파일 실행**: `poetry run pytest tests/test_filename.py`
- **커버리지와 함께 실행**: `poetry run pytest --cov=src`
- **상세 출력으로 테스트**: `poetry run pytest -v`

## 아키텍처 개요

이것은 슬래시 명령어와 접두사 명령어(`뮤` 접두사 사용) 모두를 통해 유틸리티 명령어를 제공하는 discord.py로 구축된 Discord 봇입니다.

### 핵심 구성 요소

**봇 구조**: `src/bot.py`의 메인 봇 클래스 `DiscordBot`은 `commands.Bot`을 확장하며 모든 기능을 조정합니다. 명령어는 다양한 카테고리별로 별도의 코그 클래스로 구성되어 있습니다.

**명령어 카테고리** (`src/commands/`에 위치):
- `BaseCommands`: 모든 명령어 유형에 대한 공통 기능 및 응답 처리
- `InformationCommands`: 환율, Steam 게임, 인구 데이터
- `EntertainmentCommands`: 주사위 굴리기, 투표, 가챠 게임
- `SystemCommands`: 봇 상태, 메모리 관리, 도움말
- `ArknightsCommands`: 명일방주 가챠 시뮬레이션
- `AICommands`: 채팅을 위한 Claude AI 통합
- `TeamDraftCommands`: 진행 상황 추적이 가능한 팀 드래프트 시스템

**API 서비스** (`src/services/api/`에 위치): 모든 외부 API 통합은 기본 클래스(`base.py`, `service.py`)와 특정 구현(Claude, Steam, 환율 등)을 가진 공통 패턴을 따릅니다. 속도 제한은 `rate_limit.py`에서 처리됩니다.

**메모리 시스템**: `src/services/memory_db.py`는 길드별 격리를 통해 JSON 파일 저장을 사용하여 사용자 정보의 영구 저장을 제공합니다. *(현재 개발 중)*

**메시지 처리**: `src/services/message_handler.py`는 슬래시 명령어와 접두사 명령어를 모두 처리하여 적절한 핸들러로 라우팅합니다.

### 주요 패턴

**명령어 컨텍스트**: `CommandContext` 타입 유니온을 사용하여 슬래시 및 접두사 명령어 전반에 걸쳐 `discord.Interaction`과 `commands.Context`를 균일하게 처리합니다.

**오류 처리**: `src/utils/constants.py`의 색상을 사용하여 일관된 Discord 임베드 응답으로 중앙 집중식 오류 처리.

**구성**: 봇 구성은 `src/config.py`에서 로드된 환경 변수를 통해 처리되며, 배포를 위한 git 정보 추적이 포함됩니다.

## 브랜치 전략

- `main`: 프로덕션 브랜치 (EC2로 자동 배포)
- `develop`: 개발 브랜치
- 기능 브랜치는 `develop`에서 분기해야 합니다

## 환경 설정

`.env`에 필요한 환경 변수:
```bash
DISCORD_TOKEN=your_token_here
STEAM_API_KEY=your_key_here
CL_API_KEY=your_claude_key_here  # AI 명령어용
```

로컬 개발의 경우 다음도 추가:
```bash
GIT_COMMIT=$(git rev-parse --short HEAD)
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
```

---

**참고**: 이 문서는 사람의 감독 하에 AI (Claude Code)로 작성되었습니다.