import io
import logging
from typing import List, Tuple
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

logger = logging.getLogger(__name__)

def create_player_count_chart(data: List[Tuple[float, int]], title: str) -> io.BytesIO:
    """Create a player count history chart
    
    Args:
        data: List of (timestamp, player_count) tuples
        title: Chart title (game name)
    
    Returns:
        io.BytesIO: PNG image data
    """
    try:
        # Convert timestamps to datetime objects
        dates = [datetime.fromtimestamp(ts) for ts, _ in data]
        counts = [count for _, count in data]
        
        # Create figure and axis
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(12, 6))
        
        # Plot the data
        ax.plot(dates, counts, color='#98ff98', linewidth=2)  # Light green color
        
        # Customize the chart
        ax.set_title(f"{title} - Player Count History", pad=20)
        ax.grid(True, alpha=0.2)
        
        # Format x-axis
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.xticks(rotation=45)
        
        # Format y-axis
        ax.yaxis.set_major_formatter(lambda x, p: format(int(x), ','))
        
        # Add padding
        plt.tight_layout()
        
        # Save to bytes
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=100)
        buf.seek(0)
        plt.close()
        
        return buf
        
    except Exception as e:
        logger.error(f"Failed to create chart: {e}")
        raise ValueError("Failed to create player count chart") from e 