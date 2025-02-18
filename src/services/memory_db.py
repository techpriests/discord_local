import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, TypedDict, cast

logger = logging.getLogger(__name__)


class MemoryInfo(TypedDict):
    text: str
    author: str
    timestamp: str


class MemoryDB:
    """Memory database for storing and retrieving information"""

    def __init__(self, db_file: str = "data/memory.json") -> None:
        """Initialize memory database
        
        Args:
            db_file: Path to JSON database file
        """
        self.db_file = db_file
        self._memories: Dict[str, Dict[str, MemoryInfo]] = {}
        self._load_db()

    def _load_db(self) -> None:
        """Load memories from JSON file"""
        try:
            self._ensure_db_directory()

            if not os.path.exists(self.db_file):
                self._initialize_empty_db()
                return

            data = self._read_db_file()
            self._validate_and_set_data(data)

        except Exception as e:
            self._handle_load_error(e)

    def _ensure_db_directory(self) -> None:
        """Ensure database directory exists"""
        os.makedirs(os.path.dirname(self.db_file), exist_ok=True)

    def _initialize_empty_db(self) -> None:
        """Initialize empty database"""
        self._memories = {}

    def _read_db_file(self) -> Dict[str, Any]:
        """Read database file
        
        Returns:
            Dict[str, Any]: Database contents
            
        Raises:
            ValueError: If file cannot be read or parsed
        """
        try:
            with open(self.db_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            raise ValueError(f"Failed to read database file: {e}") from e

    def _validate_and_set_data(self, data: Any) -> None:
        """Validate and set database data
        
        Args:
            data: Data to validate and set
            
        Raises:
            ValueError: If data is invalid
        """
        if not isinstance(data, dict):
            raise ValueError("Invalid database format")
        self._memories = data

    def _handle_load_error(self, error: Exception) -> None:
        """Handle database load error
        
        Args:
            error: Error that occurred
        """
        logger.error(f"Failed to load database: {error}")
        self._initialize_empty_db()

    async def store(
        self,
        nickname: str,
        text: str,
        author: Optional[str] = None
    ) -> None:
        """Store new memory
        
        Args:
            nickname: Nickname to store memory for
            text: Text content to store
            author: Optional author of the memory
        """
        if nickname not in self._memories:
            self._memories[nickname] = {}
            
        memory_id = str(uuid.uuid4())
        self._memories[nickname][memory_id] = MemoryInfo(
            text=text,
            author=author or "Unknown",
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        await self._save_db()

    async def recall(self, nickname: str) -> Dict[str, MemoryInfo]:
        """Recall memories for nickname
        
        Args:
            nickname: Nickname to recall memories for
            
        Returns:
            Dict[str, MemoryInfo]: Dictionary of memories
        """
        return self._memories.get(nickname, {})

    async def forget(self, nickname: str) -> bool:
        """Forget all memories for nickname
        
        Args:
            nickname: Nickname to forget memories for
            
        Returns:
            bool: True if memories were found and deleted
        """
        if nickname in self._memories:
            del self._memories[nickname]
            await self._save_db()
            return True
        return False

    async def _save_db(self) -> None:
        """Save database to file"""
        try:
            temp_file = self._get_temp_filename()
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self._memories, f, ensure_ascii=False, indent=2)

            # Atomic replace
            os.replace(temp_file, self.db_file)
        except Exception as e:
            logger.error(f"Failed to save database: {e}")
            if os.path.exists(temp_file):
                os.unlink(temp_file)

    def _get_temp_filename(self) -> str:
        """Get temporary filename for atomic save
        
        Returns:
            str: Temporary filename
        """
        return f"{self.db_file}.tmp"

    async def close(self) -> None:
        """Close database connection and cleanup resources"""
        try:
            await self._save_db()
        except Exception as e:
            logger.error(f"Error during database cleanup: {e}")
