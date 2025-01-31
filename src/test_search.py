import asyncio
import logging
import sys
from pathlib import Path

# Add parent directory to path to find config
sys.path.append(str(Path(__file__).parent.parent))

from services.api import APIService
from config import STEAM_API_KEY

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_searches():
    api = APIService("", STEAM_API_KEY)  # Empty string for weather_key as we don't need it
    
    test_queries = [
        # Korean games
        "라이자의 아틀리에",
        "페르소나",
        "던전앤파이터",
        
        # Japanese games
        "ペルソナ",
        "ファイナルファンタジー",
        "モンスターハンター",
        
        # Chinese games
        "原神",
        "崩坏：星穹铁道",  # Honkai: Star Rail
        
        # English games
        "Helldivers 2",
        "Counter-Strike",
        "Elden Ring",
        
        # Mixed language
        "Persona 5 ペルソナ",
        "Final Fantasy XIV 파이널 판타지",
    ]
    
    try:
        for query in test_queries:
            logger.info(f"\nTesting search for: {query}")
            game, score, similar = await api.find_game(query)
            
            if game:
                logger.info(f"Best match: {game['name']}")
                if game['names']:
                    logger.info("Localized names:")
                    for lang, name_data in game['names'].items():
                        logger.info(f"  {name_data['language']}: {name_data['name']}")
                if game['player_count']:
                    logger.info(f"Current players: {game['player_count']}")
            else:
                logger.info("No match found")
                
            if similar:
                logger.info("Similar matches:")
                for s in similar:
                    logger.info(f"  {s['name']}")
            
            # Add a small delay between searches
            await asyncio.sleep(1)
            
    finally:
        await api.close()

if __name__ == "__main__":
    asyncio.run(test_searches()) 