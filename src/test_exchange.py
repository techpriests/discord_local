import asyncio
import logging
from services.api import APIService
from config import STEAM_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_exchange_rates():
    api = APIService("", STEAM_API_KEY)
    
    try:
        logger.info("Getting exchange rates...")
        rates = await api.get_exchange_rates()
        
        # Format and display rates
        logger.info("\nExchange rates for 1000 KRW:")
        for currency, rate in rates.items():
            amount = 1000 * rate
            logger.info(f"KRW -> {currency}: {amount:.2f} {currency}")
            
    except Exception as e:
        logger.error(f"Error: {e}")
    finally:
        await api.close()

if __name__ == "__main__":
    asyncio.run(test_exchange_rates()) 