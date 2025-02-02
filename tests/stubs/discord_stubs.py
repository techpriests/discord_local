from typing import Any, Callable, Optional
from unittest.mock import AsyncMock

class MockResponse:
    send_message: AsyncMock
    defer: AsyncMock
    is_done: Callable[[], bool]

class MockInteraction:
    response: MockResponse
    followup: Any

def create_mock_interaction() -> MockInteraction:
    ... 