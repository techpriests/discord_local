from typing import Dict, List, Optional, Union, Any
from discord import Interaction
from discord.ext.commands import Context

CommandContext = Union[Context, Interaction]
JsonDict = Dict[str, Any] 