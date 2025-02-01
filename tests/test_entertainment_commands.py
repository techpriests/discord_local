import pytest
from unittest.mock import AsyncMock, MagicMock
from src.commands.entertainment import EntertainmentCommands

@pytest.fixture
def entertainment_commands():
    return EntertainmentCommands()

@pytest.mark.asyncio
async def test_dice_roll():
    commands = EntertainmentCommands()
    ctx = MagicMock()
    ctx.send = AsyncMock()
    
    # Test basic roll
    await commands._handle_roll(ctx, "1d6")
    assert ctx.send.called
    
    # Test invalid input
    await commands._handle_roll(ctx, "invalid")
    assert ctx.send.called 