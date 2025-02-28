import asyncio
import os
import logging
from src.services.api.gemini import GeminiAPI

# Set up logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_gemini_initialization():
    """Test GeminiAPI initialization and basic functionality"""
    try:
        # Get API key from environment variable
        api_key = os.getenv('GEMINI_API_KEY')
        if not api_key:
            logger.error("GEMINI_API_KEY environment variable not set")
            return False

        logger.info("Creating GeminiAPI instance...")
        gemini = GeminiAPI(api_key=api_key, notification_channel=None)

        logger.info("Testing credential validation...")
        is_valid = await gemini.validate_credentials()
        logger.info(f"Credentials valid: {is_valid}")
        if not is_valid:
            logger.error("Credential validation failed")
            return False

        logger.info("Initializing API...")
        await gemini.initialize()
        logger.info("Initialization successful")

        logger.info("Testing chat functionality...")
        response = await gemini.chat("Hello, this is a test message.", user_id=12345)
        logger.info(f"Received response: {response[:100]}...")  # Show first 100 chars

        logger.info("Getting usage stats...")
        stats = gemini.usage_stats
        logger.info(f"Current requests: {stats['daily_requests']}")

        logger.info("Getting health status...")
        health = gemini.health_status
        logger.info(f"Service enabled: {health['is_enabled']}")

        logger.info("Cleaning up...")
        await gemini.close()
        logger.info("Test completed successfully")
        return True

    except Exception as e:
        logger.error(f"Test failed: {e}")
        return False

if __name__ == "__main__":
    logger.info("Starting GeminiAPI initialization test")
    success = asyncio.run(test_gemini_initialization())
    logger.info(f"Test {'succeeded' if success else 'failed'}") 