import os
import logging
from typing import NamedTuple

logger = logging.getLogger(__name__)

class VersionInfo(NamedTuple):
    """Bot version information"""
    commit: str  # Current commit
    branch: str  # Current branch
    main_commit: str  # Main branch's latest commit
    version: str = "1.0.0"  # Semantic version

def get_git_info() -> VersionInfo:
    """Get version information from environment variables
    
    Returns:
        VersionInfo: Current version information
    """
    try:
        commit = os.getenv("GIT_COMMIT", "unknown")
        branch = os.getenv("GIT_BRANCH", "unknown")
        main_commit = os.getenv("GIT_MAIN_COMMIT", "unknown")
        
        return VersionInfo(
            commit=commit,
            branch=branch,
            main_commit=main_commit
        )
    except Exception as e:
        logger.error(f"Failed to get version info: {e}")
        return VersionInfo(
            commit="unknown",
            branch="unknown",
            main_commit="unknown"
        ) 