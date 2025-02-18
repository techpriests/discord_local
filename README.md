# Discord Utility Bot

A Discord bot with various utility commands including:
- Exchange rate conversion
- Steam game information
- Population statistics
- Memory system for user information

## Features

### Slash Commands
- `/exchange [currency] [amount]` - Convert currencies
- `/steam [game]` - Get Steam game info
- `/population [country]` - Get country population
- `/remember [text] [nickname]` - Store information
- `/recall [nickname]` - Recall stored information
- `/forget [nickname]` - Delete stored information

### Prefix Commands (using !!, 프틸, pt)
Same functionality as slash commands with prefixes:
- `!!command`
- `프틸 command`
- `pt command`

## Development

### Requirements
- Python 3.12+
- Docker
- Discord Bot Token
- Steam API Key

### Setup
1. Clone repository
2. Create `.env` file with:
   ```bash
   # Required API keys
   DISCORD_TOKEN=your_token_here
   STEAM_API_KEY=your_key_here
   
   # For local development, run these commands:
   # echo "GIT_COMMIT=$(git rev-parse --short HEAD)" >> .env
   # echo "GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD)" >> .env
   ```
   Note: In CI/CD, Git information is handled automatically.
3. Install dependencies: `pip install -e .`
4. Run with Docker: `docker-compose up -d`

### Branch Structure
- `main`: Production branch, deploys to EC2
- `develop`: Development branch
- Feature branches branch from `develop`
