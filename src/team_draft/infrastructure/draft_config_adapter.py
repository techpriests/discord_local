"""
Draft Configuration Adapter

Adapter for draft configuration settings.
Preserves existing configuration from the original system.
"""

from typing import Dict, List, Any
from ..application.interfaces import IDraftConfiguration


class DraftConfigurationAdapter(IDraftConfiguration):
    """
    Configuration adapter that preserves existing draft settings.
    
    Centralizes all configuration values from the original system.
    """
    
    def get_team_selection_patterns(self) -> Dict[int, List[Dict[str, int]]]:
        """Get team selection patterns for different team sizes - preserves existing patterns"""
        return {
            2: [  # 2v2 pattern
                {"first_pick": 1, "second_pick": 1},  # Round 1: Each captain picks 1
            ],
            3: [  # 3v3 pattern
                {"first_pick": 1, "second_pick": 2},  # Round 1: First picks 1, Second picks 2
                {"first_pick": 1, "second_pick": 0},  # Round 2: First picks 1, Second picks 0
            ],
            5: [  # 5v5 pattern
                {"first_pick": 1, "second_pick": 2},  # Round 1: First picks 1, Second picks 2
                {"first_pick": 2, "second_pick": 2},  # Round 2: Each picks 2
            ],
            6: [  # 6v6 pattern
                {"first_pick": 1, "second_pick": 2},  # Round 1: First picks 1, Second picks 2
                {"first_pick": 2, "second_pick": 2},  # Round 2: Each picks 2
                {"first_pick": 1, "second_pick": 0},  # Round 3: First picks 1, Second picks 0
            ]
        }
    
    def get_time_limits(self) -> Dict[str, int]:
        """Get time limits for different phases - preserves existing limits"""
        return {
            "captain_voting": 120,      # 2 minutes
            "servant_selection": 90,    # 1 minute 30 seconds
            "servant_reselection": 90,  # 1 minute 30 seconds
            "team_selection": 300       # 5 minutes (no specific limit in original, setting reasonable default)
        }
    
    def get_servant_configuration(self) -> Dict[str, Any]:
        """Get servant configuration - preserves existing servant setup"""
        return {
            "tiers": {
                "S": ["헤클", "길가", "란슬", "가재"],
                "A": ["세이버", "네로", "카르나", "룰러"],
                "B": ["디미", "이칸", "산노", "서문", "바토리"]
            },
            "categories": {
                "세이버": ["세이버", "흑화 세이버", "가웨인", "네로", "모드레드", "무사시", "지크"],
                "랜서": ["쿠훌린", "디미", "가재", "카르나", "바토리"],
                "아처": ["아처", "길가", "아엑", "아탈"],
                "라이더": ["메두사", "이칸", "라엑", "톨포"],
                "캐스터": ["메데이아", "질드레", "타마", "너서리", "셰익", "안데"],
                "어새신": ["허새", "징어", "서문", "잭더리퍼", "세미", "산노", "시키"],
                "버서커": ["헤클", "란슬", "여포", "프랑"],
                "엑스트라": ["어벤저", "룰러", "멜트", "암굴"]
            },
            "available_servants": {
                # Flatten all categories into a single set
                "세이버", "흑화 세이버", "가웨인", "네로", "모드레드", "무사시", "지크",
                "쿠훌린", "디미", "가재", "카르나", "바토리",
                "아처", "길가", "아엑", "아탈",
                "메두사", "이칸", "라엑", "톨포",
                "메데이아", "질드레", "타마", "너서리", "셰익", "안데",
                "허새", "징어", "서문", "잭더리퍼", "세미", "산노", "시키",
                "헤클", "란슬", "여포", "프랑",
                "어벤저", "룰러", "멜트", "암굴"
            },
            "special_abilities": {
                "detection": ["아처", "룰러", "너서리", "아탈", "가웨인", "디미", "허새"],
                "cloaking": ["서문", "징어", "잭더리퍼", "세미", "안데"]
            }
        }
    
    def get_allowed_team_sizes(self) -> List[int]:
        """Get allowed team sizes"""
        return [2, 3, 5, 6]
    
    def get_default_team_size(self) -> int:
        """Get default team size"""
        return 6
    
    def get_default_total_players(self) -> int:
        """Get default total players for join-based drafts"""
        return 12
    
    def get_ui_settings(self) -> Dict[str, Any]:
        """Get UI-related settings"""
        return {
            "embed_colors": {
                "info": 0x3498db,      # Blue
                "success": 0x2ecc71,   # Green  
                "error": 0xe74c3c,     # Red
                "warning": 0xf39c12    # Orange
            },
            "button_styles": {
                "primary": "primary",
                "success": "success", 
                "secondary": "secondary",
                "danger": "danger"
            },
            "timeouts": {
                "view_timeout": 300,    # 5 minutes
                "interaction_timeout": 15  # 15 seconds
            }
        }
