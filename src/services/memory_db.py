import json
import os
from typing import Dict, Optional, TypedDict
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class MemoryInfo(TypedDict):
    text: str
    author: str
    timestamp: str

class MemoryDB:
    def __init__(self, db_file: str = 'data/memory.json'):
        self.db_file = db_file
        self.memories: Dict[str, Dict[str, MemoryInfo]] = {}
        self._load_db()
    
    def _load_db(self):
        """Load memories from JSON file"""
        try:
            os.makedirs(os.path.dirname(self.db_file), exist_ok=True)
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    self.memories = json.load(f)
        except Exception as e:
            logger.error(f"Error loading memory database: {e}")
            self.memories = {}
    
    def _save_db(self):
        """Save memories to JSON file"""
        try:
            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.memories, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving memory database: {e}")
    
    def remember(self, text: str, user_nickname: str, author: str) -> bool:
        """Store a memory about a user with author and timestamp
        
        Args:
            text: The information to store
            user_nickname: The user the information is about
            author: Discord username of who added this information
        """
        try:
            if user_nickname not in self.memories:
                self.memories[user_nickname] = {}
                
            # Store text with metadata
            self.memories[user_nickname][text] = {
                'text': text,
                'author': author,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            self._save_db()
            return True
        except Exception as e:
            logger.error(f"Error storing memory: {e}")
            return False
    
    def recall(self, user_nickname: str) -> Optional[Dict[str, MemoryInfo]]:
        """Recall memories about a specific user"""
        return self.memories.get(user_nickname)
    
    def forget(self, user_nickname: str) -> bool:
        """Delete all memories about a user"""
        try:
            if user_nickname in self.memories:
                del self.memories[user_nickname]
                self._save_db()
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting memories: {e}")
            return False 