"""NewsFollower - keep only the news and price action that can be traded."""

from .config import MoveConfig, NewsConfig, PipelineConfig
from .criticality import NewsScore, score_news
from .dedup import Deduper, similarity
from .models import Alert, Move, NewsItem, Priority, Tick
from .pipeline import NewsFollower
from .price_action import QuickMoveDetector

__all__ = [
    "Alert", "Deduper", "Move", "MoveConfig", "NewsConfig", "NewsFollower",
    "NewsItem", "NewsScore", "PipelineConfig", "Priority", "QuickMoveDetector",
    "Tick", "score_news", "similarity",
]
__version__ = "0.1.0"
