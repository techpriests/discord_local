from typing import TypedDict, List, Optional

class PollOption(TypedDict):
    name: str
    votes: int

class Poll(TypedDict):
    title: str
    options: List[PollOption]
    voters: List[int]  # List of user IDs
    is_active: bool
    max_votes: Optional[int] 