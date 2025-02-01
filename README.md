# Discord Utility Bot

A Discord bot with various utility commands including:
- Exchange rate conversion
- Steam game information
- Weather updates
- Population statistics
- Memory system for user information

## Features

### Slash Commands
- `/exchange [currency] [amount]` - Convert currencies
- `/steam [game]` - Get Steam game info
- `/weather` - Get Seoul weather
- `/population [country]` - Get country population
- `/remember [text] [nickname]` - Store information
- `/recall [nickname]` - Recall stored information
- `/forget [nickname]` - Delete stored information

### Prefix Commands (using !!)
Same functionality as slash commands with prefix `!!`

## Development

### Requirements
- Python 3.12+
- Docker
- Discord Bot Token
- Steam API Key
- Weather API Key

### Setup
1. Clone repository
2. Copy `config.example.py` to `config.py` and add your API keys
3. Install dependencies: `pip install -e .`
4. Run with Docker: `docker-compose up -d`

### Branch Structure
- `main`: Production branch, deploys to EC2
- `develop`: Development branch
- Feature branches branch from `develop`
