import subprocess
from typing import NamedTuple
import logging

logger = logging.getLogger(__name__)

class VersionInfo(NamedTuple):
    """Bot version information"""
    commit: str
    branch: str
    version: str = "1.0.0"  # Semantic version

def get_git_info() -> VersionInfo:
    """Get current git commit and branch information
    
    Returns:
        VersionInfo: Current version information
    """
    try:
        commit = subprocess.check_output(
            ['git', 'rev-parse', '--short', 'HEAD'],
            text=True
        ).strip()
        
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            text=True
        ).strip()
        
        return VersionInfo(commit=commit, branch=branch)
    except Exception as e:
        logger.error(f"Failed to get git info: {e}")
        return VersionInfo(commit="unknown", branch="unknown") 