# Mumu-discord

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Docker](https://img.shields.io/badge/docker-enabled-blue)](https://www.docker.com/)
[![Poetry](https://img.shields.io/badge/dependency-poetry-blue)](https://python-poetry.org/)

**Language**: [English](README.md) | [한국어](README.ko.md)

A Discord bot providing utility commands, AI integration, and entertainment features through both slash commands and traditional prefix commands. Built with AI assistance under human supervision and designed for easy deployment and scaling.

## Features

### Information & Utilities
- **Currency Exchange**: Real-time currency conversion with up-to-date rates (No longer maintained at the moment)
- **Steam Game Info**: Comprehensive game details and pricing

### Entertainment
- **Dice Rolling**: Customizable dice games and random number generation
- **Interactive Polls**: Community voting with real-time results
- **Gacha Games**: Arknights gacha simulation

### AI Integration
- **Claude AI Chat**: Natural language conversations powered by Anthropic's Claude(Supports web search tool)

### Team Management
- **Draft System**: Advanced team drafting with progress tracking
- **Guild Isolation**: Per-server data management and customization

### Development Features
- **Hot Reload**: Live module reloading without bot restart (supports: InformationCommands, EntertainmentCommands, SystemCommands, ArknightsCommands, AICommands, TeamDraftCommands)

## Quick Start

### Option 1: Docker (Recommended)
```bash
# Clone the repository
git clone https://github.com/techpriests/mumu-discord.git
cd mumu-discord

# Set up environment variables
cp env.example .env
# Edit .env with your API keys

# Launch with Docker
docker-compose up -d
```

### Option 2: Local Development
```bash
# Install dependencies
poetry install

# Set up environment
echo "GIT_COMMIT=$(git rev-parse --short HEAD)" >> .env
echo "GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)" >> .env

# Run the bot
poetry run python -m src.bot
```

## Commands

### Slash Commands
| Command | Description | Example |
|---------|-------------|---------|
| `/exchange` | Convert currencies | `/exchange USD 100 EUR` |
| `/steam` | Get Steam game info | `/steam "Cyberpunk 2077"` |
| `/population` | Country population data | `/population Japan` |
| `/remember` | Store information | `/remember "Meeting at 3PM" meeting-today` |
| `/recall` | Retrieve information | `/recall meeting-today` |

### Prefix Commands
All slash commands work with prefixes: `뮤`
```
!!exchange USD 100 EUR
뮤 steam Cyberpunk 2077
pt population Japan
```

## Development

### Prerequisites
- Python 3.12+
- Docker & Docker Compose
- Poetry (for dependency management)
- Discord Bot Token
- API Keys (Steam, Claude AI)

### Environment Setup
Create a `.env` file with your API credentials:
```bash
# Required
DISCORD_TOKEN=your_discord_bot_token
STEAM_API_KEY=your_steam_api_key
CL_API_KEY=your_claude_api_key

# Development (auto-generated in CI/CD)
GIT_COMMIT=your_git_commit_hash
GIT_BRANCH=your_current_branch
```

### Development Commands
```bash
# Install dependencies
poetry install

# Run tests
poetry run pytest

# Type checking
poetry run mypy src/

# Code formatting
poetry run black src/
poetry run isort src/

# Linting
poetry run ruff check src/
```

### Docker Development
```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f bot

# Stop services
docker-compose down
```

## Architecture

- **Modular Design**: Commands organized into logical cogs
- **API Abstraction**: Unified service layer for external APIs
- **Error Handling**: Comprehensive error management with user-friendly responses
- **Memory System**: Persistent storage with guild isolation (under development)
- **Rate Limiting**: Built-in API rate limiting and request management

For detailed architecture information, see [CLAUDE.md](docs/CLAUDE.md).

## Contributing

We welcome contributions! Please see our [Contributing Guidelines](docs/CONTRIBUTING.md) for details.

1. Fork the repository
2. Create a feature branch from `develop`
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

### Branch Strategy
- `main`: Production deployment
- `develop`: Development integration
- `feature/*`: New features and improvements

## Security

For security concerns, please review our [Security Policy](docs/SECURITY.md) or contact the maintainers directly.

## Documentation

- [Architecture Overview](docs/CLAUDE.md)
- [Contributing Guidelines](docs/CONTRIBUTING.md)
- [Security Policy](docs/SECURITY.md)

---

**Note**: This documentation was written with AI (Claude Code) under human supervision.

Built with care using Python, Discord.py, and modern development practices.
