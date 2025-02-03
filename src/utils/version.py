import os
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)

class VersionInfo(NamedTuple):
    """Bot version information"""
    commit: str  # Current commit
    branch: str  # Current branch
    version: str = "1.0.0"  # Semantic version

def get_git_info() -> VersionInfo:
    """Get version information from environment variables
    
    Returns:
        VersionInfo: Current version information
    """
    try:
        commit = os.getenv("GIT_COMMIT", "unknown")
        branch = os.getenv("GIT_BRANCH", "unknown")
        
        return VersionInfo(
            commit=commit,
            branch=branch
        )
    except Exception as e:
        logger.error(f"Failed to get version info: {e}")
        return VersionInfo(
            commit="unknown",
            branch="unknown"
        ) 