import pytest
import os
import json
from src.services.memory_db import MemoryDB

@pytest.fixture
def memory_db():
    db = MemoryDB()
    yield db
    # Cleanup after tests
    if os.path.exists('memories.json'):
        os.remove('memories.json')

def test_remember(memory_db):
    # Test storing new memory
    assert memory_db.remember("test info", "test_nick", "test_author")
    
    # Verify memory was stored
    assert "test_nick" in memory_db.memories
    stored_memory = memory_db.memories["test_nick"]
    assert any(mem['text'] == "test info" for mem in stored_memory.values())

def test_recall(memory_db):
    # Store test memory
    memory_db.remember("test info", "test_nick", "test_author")
    
    # Test recall
    memories = memory_db.recall("test_nick")
    assert memories is not None
    assert len(memories) > 0
    
    # Verify content
    memory = list(memories.values())[0]
    assert memory['text'] == "test info"
    assert memory['author'] == "test_author"

def test_forget(memory_db):
    # Store test memory
    memory_db.remember("test info", "test_nick", "test_author")
    
    # Test forget
    assert memory_db.forget("test_nick")
    assert "test_nick" not in memory_db.memories

def test_save_and_load(memory_db):
    # Store test memory
    memory_db.remember("test info", "test_nick", "test_author")
    
    # Create new instance to test loading
    new_db = MemoryDB()
    assert "test_nick" in new_db.memories
    
    memory = list(new_db.memories["test_nick"].values())[0]
    assert memory['text'] == "test info"
