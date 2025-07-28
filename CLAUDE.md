# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Core Commands
- **Install dependencies**: `poetry install`
- **Run tests**: `poetry run pytest`
- **Type checking**: `poetry run mypy src/`
- **Linting**: `poetry run ruff check src/`
- **Code formatting**: `poetry run black src/`
- **Import sorting**: `poetry run isort src/`

### Docker Development
- **Build and run bot**: `docker-compose up -d`
- **View logs**: `docker-compose logs -f bot`
- **Stop bot**: `docker-compose down`

### Testing
- **Run specific test file**: `poetry run pytest tests/test_filename.py`
- **Run with coverage**: `poetry run pytest --cov=src`
- **Test with verbose output**: `poetry run pytest -v`

## Architecture Overview

This is a Discord bot built with discord.py that provides utility commands through both slash commands and prefix commands (using `뮤` prefix).

### Core Components

**Bot Structure**: The main bot class `DiscordBot` in `src/bot.py` extends `commands.Bot` and coordinates all functionality. Commands are organized into separate cog classes for different categories.

**Command Categories** (in `src/commands/`):
- `BaseCommands`: Common functionality and response handling for all command types
- `InformationCommands`: Exchange rates, Steam games, population data
- `EntertainmentCommands`: Dice rolling, polls, gacha games
- `SystemCommands`: Bot status, memory management, help
- `ArknightsCommands`: Arknights gacha simulation
- `AICommands`: Claude AI integration for chat
- `TeamDraftCommands`: Team drafting system with progress tracking

**API Services** (in `src/services/api/`): All external API integrations follow a common pattern with base classes (`base.py`, `service.py`) and specific implementations (Claude, Steam, exchange rates, etc.). Rate limiting is handled in `rate_limit.py`.

**Memory System**: `src/services/memory_db.py` provides persistent storage for user information using JSON file storage with per-guild isolation. *(Currently under development)*

**Message Handling**: `src/services/message_handler.py` processes both slash commands and prefix commands, routing them to appropriate handlers.

### Key Patterns

**Command Context**: Uses `CommandContext` type union to handle both `discord.Interaction` and `commands.Context` uniformly across slash and prefix commands.

**Error Handling**: Centralized error handling with consistent Discord embed responses using colors from `src/utils/constants.py`.

**Configuration**: Bot configuration is handled through environment variables loaded in `src/config.py`, with git information tracking for deployment.

## Branch Strategy

- `main`: Production branch (auto-deploys to EC2)
- `develop`: Development branch
- Feature branches should branch from `develop`

## Environment Setup

Required environment variables in `.env`:
```bash
DISCORD_TOKEN=your_token_here
STEAM_API_KEY=your_key_here
CL_API_KEY=your_claude_key_here  # For AI commands
```

For local development, also add:
```bash
GIT_COMMIT=$(git rev-parse --short HEAD)
GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
```

---

**Note**: This documentation was written with AI (Claude Code) under human supervision.