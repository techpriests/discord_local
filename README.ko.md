# Mumu-discord

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-enabled-blue)](https://www.docker.com/)
[![Poetry](https://img.shields.io/badge/dependency-poetry-blue)](https://python-poetry.org/)

**언어**: [English](README.md) | [한국어](README.ko.md)

슬래시 명령어와 접두사 명령어를 통해 Claude AI 채팅, 여러 정보 및 엔터테인먼트 기능을 제공하는 Discord 봇입니다. 사람의 감독 하에 AI로 작성되었으며, 쉬운 배포와 확장성을 위해 설계되었습니다.

## 기능

### 정보 및 유틸리티
- **환율 변환**: 실시간 환율을 이용한 통화 변환 (현재 유지관리되지 않음)
- **Steam 게임 정보**: 스팀 게임 상세 정보 및 가격

### 엔터테인먼트
- **주사위 굴리기**: 사용자 정의 가능한 주사위 굴리기 기능
- **대화형 투표**: 실시간 결과를 보여주는 투표
- **가챠 게임**: 명일방주 가챠 시뮬레이션

### AI
- **Claude AI 채팅**: Anthropic의 Claude로 구동되는 자연어 대화(웹 검색 지원)

### 팀 관리
- **드래프트 시스템**: 진행 상황 추적이 가능한 고급 팀 드래프트
- **길드 격리**: 서버별 데이터 관리 및 사용자 정의

### 개발 기능
- **핫 리로드**: 봇 재시작 없이 실시간 모듈 다시 로드 (지원: InformationCommands, EntertainmentCommands, SystemCommands, ArknightsCommands, AICommands, TeamDraftCommands)

## 빠른 시작

### 옵션 1: Docker (권장)
```bash
# 저장소 복제
git clone https://github.com/techpriests/mumu-discord.git
cd mumu-discord

# 환경 변수 설정
cp env.example .env
# .env 파일을 API 키로 편집

# Docker로 실행
docker-compose up -d
```

### 옵션 2: 로컬 개발
```bash
# 의존성 설치
poetry install

# 환경 설정
echo "GIT_COMMIT=$(git rev-parse --short HEAD)" >> .env
echo "GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)" >> .env

# 봇 실행
poetry run python -m src.bot
```

## 명령어

### 슬래시 명령어
| 명령어 | 설명 | 예시 |
|---------|-------------|---------|
| `/exchange` | 통화 변환 | `/exchange USD 100 EUR` |
| `/steam` | Steam 게임 정보 조회 | `/steam "Cyberpunk 2077"` |
| `/population` | 국가 인구 데이터 | `/population Japan` |
| `/remember` | 정보 저장 | `/remember "3시에 회의" meeting-today` |
| `/recall` | 정보 불러오기 | `/recall meeting-today` |

### 접두사 명령어
모든 슬래시 명령어는 접두사와 함께 작동합니다: `뮤`
```
!!exchange USD 100 EUR
뮤 steam Cyberpunk 2077
pt population Japan
```

## 개발

### 필수 조건
- Python 3.12+
- Docker 및 Docker Compose
- Poetry (의존성 관리용)
- Discord Bot 토큰
- API 키 (Steam, Claude AI)

### 환경 설정
API 자격 증명으로 `.env` 파일을 생성하세요:
```bash
# 필수
DISCORD_TOKEN=your_discord_bot_token
STEAM_API_KEY=your_steam_api_key
CL_API_KEY=your_claude_api_key

# 개발용 (CI/CD에서 자동 생성)
GIT_COMMIT=your_git_commit_hash
GIT_BRANCH=your_current_branch
```

### 개발 명령어
```bash
# 의존성 설치
poetry install

# 테스트 실행
poetry run pytest

# 타입 체크
poetry run mypy src/

# 코드 포맷팅
poetry run black src/
poetry run isort src/

# 린팅
poetry run ruff check src/
```

### Docker 개발
```bash
# 빌드 및 실행
docker-compose up -d

# 로그 보기
docker-compose logs -f bot

# 서비스 중지
docker-compose down
```

## 아키텍처

- **모듈식 설계**: 논리적 cogs로 구성된 명령어
- **API 추상화**: 외부 API를 위한 통합 서비스 계층
- **오류 처리**: 사용자 친화적 응답을 갖춘 포괄적인 오류 관리
- **메모리 시스템**: 길드 격리가 가능한 영구 저장소 (개발 중)
- **속도 제한**: 내장된 API 속도 제한 및 요청 관리

자세한 아키텍처 정보는 [CLAUDE.ko.md](docs/CLAUDE.ko.md)를 참조하세요.

## 기여

기여를 환영합니다! 자세한 내용은 [기여 가이드라인](docs/CONTRIBUTING.ko.md)을 참조하세요.

1. 저장소를 포크하세요
2. `develop`에서 기능 브랜치를 생성하세요
3. 변경 사항을 만드세요
4. 새로운 기능에 대한 테스트를 추가하세요
5. PR을 제출하세요

### 브랜치 전략
- `main`: 프로덕션 배포
- `develop`: 개발 통합
- `feature/*`: 새로운 기능 및 개선사항

## 보안

보안 문제에 대해서는 [보안 정책](docs/SECURITY.ko.md)을 검토하거나 유지관리자에게 직접 연락하세요.

## 문서

- [아키텍처 개요](docs/CLAUDE.ko.md)
- [기여 가이드라인](docs/CONTRIBUTING.ko.md)
- [보안 정책](docs/SECURITY.ko.md)

---

**참고**: 이 문서는 사람의 감독 하에 AI (Claude Code)로 작성되었습니다.

Python, Discord.py, 그리고 최신 개발 관례를 사용하여 정성껏 제작되었습니다.