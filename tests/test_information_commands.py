import pytest
from unittest.mock import MagicMock, AsyncMock
import discord
from discord.ext import commands

@pytest.mark.asyncio
class TestInformationCommands:
    """Test information commands functionality"""

    async def test_population_command(self, bot, mock_context):
        """Test population command with different prefixes"""
        # Mock API response
        mock_country_info = {
            'name': {'official': 'Test Country'},
            'population': 1000000,
            'capital': ['Test City'],
            'region': 'Test Region',
            'flags': {'png': 'http://test.com/flag.png'}
        }
        bot._api_service.population.get_country_info = AsyncMock(return_value=mock_country_info)

        test_cases = [
            ("!!인구", "인구", "South Korea"),
            ("뮤 인구", "인구", "Japan"),
            ("pt population", "population", "USA")
        ]

        for prefix, cmd, country in test_cases:
            # Reset mock for each test case
            mock_context.reset_mock()
            
            # Set up message content
            mock_context.message.content = f"{prefix} {country}"
            mock_context.prefix = prefix
            mock_context.invoked_with = cmd
            mock_context.command = bot.get_command(cmd)

            # Process command
            command = bot.get_command(cmd)
            assert command is not None
            assert command.name in ['인구', 'population']

            # Execute command with proper context
            await command(mock_context)

            # Verify embed was sent
            mock_context.send.assert_called_once()

    async def test_steam_command(self, bot, mock_context):
        """Test steam command with different prefixes"""
        # Mock API response
        mock_game_info = {
            'name': 'Test Game',
            'player_count': 10000,
            'image_url': 'http://test.com/game.jpg'
        }
        bot._api_service.steam.find_game = AsyncMock(return_value=(mock_game_info, 1.0, []))

        test_cases = [
            ("!!스팀", "스팀", "Lost Ark"),
            ("뮤 스팀", "스팀", "PUBG"),
            ("pt steam", "steam", "Dota 2")
        ]

        for prefix, cmd, game in test_cases:
            # Reset mock for each test case
            mock_context.reset_mock()
            
            # Set up message content
            mock_context.message.content = f"{prefix} {game}"
            mock_context.prefix = prefix
            mock_context.invoked_with = cmd
            mock_context.command = bot.get_command(cmd)

            # Process command
            command = bot.get_command(cmd)
            assert command is not None
            assert command.name in ['스팀', 'steam']

            # Execute command with proper context
            await command(mock_context)

            # Verify embed was sent
            mock_context.send.assert_called_once()

    async def test_time_command(self, bot, mock_context):
        """Test time command with different prefixes"""
        test_cases = [
            ("!!시간", "시간", "US/Pacific"),
            ("뮤 시간", "시간", "Asia/Seoul"),
            ("pt time", "time", "Europe/London")
        ]

        for prefix, cmd, timezone in test_cases:
            # Reset mock for each test case
            mock_context.reset_mock()
            
            # Set up message content
            mock_context.message.content = f"{prefix} {timezone}"
            mock_context.prefix = prefix
            mock_context.invoked_with = cmd
            mock_context.command = bot.get_command(cmd)

            # Process command
            command = bot.get_command(cmd)
            assert command is not None
            assert command.name in ['시간', 'time']

            # Execute command with proper context
            await command(mock_context)

            # Verify embed was sent
            mock_context.send.assert_called_once()

    async def test_exchange_command(self, bot, mock_context):
        """Test exchange command with different prefixes"""
        # Mock API response
        mock_rates = {
            'USD': 1200.0,
            'EUR': 1400.0,
            'JPY': 11.0,
        }
        bot._api_service.exchange.get_exchange_rates = AsyncMock(return_value=mock_rates)

        test_cases = [
            ("!!환율", "환율", None),
            ("뮤 환율", "환율", "USD"),
            ("pt exchange", "exchange", "EUR")
        ]

        for prefix, cmd, currency in test_cases:
            # Reset mock for each test case
            mock_context.reset_mock()
            mock_context.send.reset_mock()  # Explicitly reset send mock
            
            # Set up message content
            content = f"{prefix}"
            if currency:
                content = f"{content} {currency}"
            mock_context.message.content = content
            mock_context.prefix = prefix
            mock_context.invoked_with = cmd
            mock_context.command = bot.get_command(cmd)

            # Process command
            command = bot.get_command(cmd)
            assert command is not None
            assert command.name in ['환율', 'exchange']

            # Execute command with proper context
            await command(mock_context)

            # Verify that send was called twice (processing + result)
            assert mock_context.send.call_count == 2, f"Expected two calls, got {mock_context.send.call_count}"
            
            # Verify both calls have embeds
            first_call = mock_context.send.call_args_list[0]
            last_call = mock_context.send.call_args_list[-1]
            
            # First call should be processing message
            first_embed = first_call.kwargs.get('embed')
            assert isinstance(first_embed, discord.Embed), "First call should have an embed"
            assert first_embed.description is not None, "Processing embed should have a description"
            assert "환율 정보를 가져오고 있어" in first_embed.description, "Processing message not found in first embed"
            
            # Last call should be exchange rate embed
            last_embed = last_call.kwargs.get('embed')
            assert isinstance(last_embed, discord.Embed), "Last call should have an embed"
            assert "💱" in last_embed.title, "Exchange rate embed should have currency symbol in title"

    async def test_weather_command_removed(self, bot, mock_context):
        """Test that weather command is properly removed"""
        test_cases = [
            "!!날씨 Seoul",
            "뮤 날씨 Tokyo",
            "pt weather London"
        ]

        for msg in test_cases:
            mock_context.message.content = msg
            mock_context.prefix = msg.split()[0]
            mock_context.invoked_with = msg.split()[1]
            
            # Verify command doesn't exist
            command = bot.get_command(mock_context.invoked_with)
            assert command is None 