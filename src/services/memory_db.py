import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, Optional, TypedDict

logger = logging.getLogger(__name__)


class MemoryInfo(TypedDict):
    text: str
    author: str
    timestamp: str


class MemoryDB:
    def __init__(self, db_file: str = "data/memory.json"):
        """Initialize memory database

        Args:
            db_file: Path to JSON database file
        """
        self.db_file = db_file
        self.memories: Dict[str, Dict[str, MemoryInfo]] = {}
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
        self.memories = {}

    def _read_db_file(self) -> dict:
        """Read database file

        Returns:
            dict: Database contents

        Raises:
            json.JSONDecodeError: If file contains invalid JSON
            OSError: If file cannot be read
        """
        with open(self.db_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def _validate_and_set_data(self, data: Any) -> None:
        """Validate and set database data

        Args:
            data: Data to validate and set

        Raises:
            ValueError: If data is invalid
        """
        if not isinstance(data, dict):
            raise ValueError("Invalid database format")
        self.memories = data

    def _handle_load_error(self, error: Exception) -> None:
        """Handle database load error

        Args:
            error: The error that occurred
        """
        error_type = type(error).__name__
        logger.error(f"Failed to load memory database: [{error_type}] {error}")
        self._initialize_empty_db()

    def _save_db(self) -> None:
        """Save memories to JSON file

        Raises:
            OSError: If directory creation or file write fails
            ValueError: If memory data cannot be serialized
        """
        try:
            self._ensure_db_directory()
            self._write_to_temp_file()
            self._replace_with_temp_file()

        except OSError as e:
            self._handle_save_error("메모리 DB 저장 실패", e)
        except TypeError as e:
            self._handle_save_error("메모리 데이터 직렬화 실패", e)
        except Exception as e:
            self._handle_save_error("메모리 DB 저장 중 오류 발생", e)

    def _write_to_temp_file(self) -> None:
        """Write memory data to temporary file

        Raises:
            OSError: If file write fails
            TypeError: If data cannot be serialized
        """
        temp_file = self._get_temp_filename()
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(self.memories, f, ensure_ascii=False, indent=2)

    def _get_temp_filename(self) -> str:
        """Get temporary file name

        Returns:
            str: Temporary file path
        """
        return f"{self.db_file}.tmp"

    def _replace_with_temp_file(self) -> None:
        """Replace main file with temporary file

        Raises:
            OSError: If file replacement fails
        """
        temp_file = self._get_temp_filename()
        os.replace(temp_file, self.db_file)

    def _handle_save_error(self, message: str, error: Exception) -> None:
        """Handle database save error

        Args:
            message: Error message prefix
            error: The error that occurred

        Raises:
            ValueError: With formatted error message
        """
        error_type = type(error).__name__
        logger.error(f"Failed to save memory database: [{error_type}] {error}")
        raise ValueError(f"{message}: {str(error)}") from error

    def remember(self, text: str, user_nickname: str, author: str) -> bool:
        """Store a memory about a user

        Args:
            text: The information to store
            user_nickname: The user the information is about
            author: Discord username of who added this information

        Returns:
            bool: True if memory was stored successfully

        Raises:
            ValueError: If input validation fails
        """
        try:
            self._validate_memory_input(text, user_nickname, author)
            memory_info = self._create_memory_info(text, author)
            self._store_memory(user_nickname, memory_info)
            self._save_db()
            return True

        except ValueError as e:
            logger.error(f"Memory validation error: {e}")
            return False
        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            return False

    def _validate_memory_input(self, text: str, user_nickname: str, author: str) -> None:
        """Validate memory input parameters

        Args:
            text: The information to store
            user_nickname: The user the information is about
            author: Discord username of who added this information

        Raises:
            ValueError: If any validation fails
        """
        if not text or not user_nickname or not author:
            raise ValueError("All fields must be non-empty")

        if len(text) > 1000:
            raise ValueError("Text is too long (max: 1000 characters)")

        if len(user_nickname) > 100:
            raise ValueError("Nickname is too long (max: 100 characters)")

    def _create_memory_info(self, text: str, author: str) -> Dict[str, str]:
        """Create memory info dictionary

        Args:
            text: The information to store
            author: Discord username of who added this information

        Returns:
            Dict[str, str]: Memory info dictionary
        """
        return {
            "text": text,
            "author": author,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _store_memory(self, user_nickname: str, memory_info: Dict[str, str]) -> None:
        """Store memory in database

        Args:
            user_nickname: The user the information is about
            memory_info: Memory information dictionary
        """
        if user_nickname not in self.memories:
            self.memories[user_nickname] = {}

        memory_id = str(uuid.uuid4())
        self.memories[user_nickname][memory_id] = memory_info

    def recall(self, user_nickname: str) -> Optional[Dict[str, MemoryInfo]]:
        """Recall memories about a specific user

        Args:
            user_nickname: User to recall memories for

        Returns:
            Optional[Dict[str, MemoryInfo]]: Dictionary of memories or None if not found
        """
        try:
            return self.memories.get(user_nickname)
        except Exception as e:
            logger.error(f"Error recalling memories for {user_nickname}: {e}")
            return None

    def forget(self, user_nickname: str) -> bool:
        """Delete all memories about a user

        Args:
            user_nickname: User to forget memories for

        Returns:
            bool: True if memories were deleted successfully
        """
        try:
            if not self._has_memories(user_nickname):
                return False

            self._delete_memories(user_nickname)
            self._save_db()
            return True

        except Exception as e:
            logger.error(f"Error deleting memories for {user_nickname}: {e}")
            return False

    def _has_memories(self, user_nickname: str) -> bool:
        """Check if user has any stored memories

        Args:
            user_nickname: User to check memories for

        Returns:
            bool: True if user has memories
        """
        return user_nickname in self.memories

    def _delete_memories(self, user_nickname: str) -> None:
        """Delete all memories for a user

        Args:
            user_nickname: User to delete memories for
        """
        del self.memories[user_nickname]
