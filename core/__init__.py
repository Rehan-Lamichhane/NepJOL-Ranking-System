# core/__init__.py

"""
NepJOL Ranking System - Core Functional Engines
This file exposes the main pipeline and scraping modules to the rest of the application ecosystem.
"""

# Package-level structural versions tracking
__version__ = "1.0.0"
__author__ = "Madan Khadka, Rehan Lamichhane, Sagar Karki, Saurav Kumar Mishra"

# Expose internal functional methods cleanly at the package root level
from core.pipeline import process_ml_rankings
from core.scraper import run_nepjol_scraper
from core.cache import CacheManager, CheckpointManager
from core.config import ScraperConfig, CONFIG
from core.network import NetworkSession, RateLimiter, RobotsChecker
from core.validators import validate_issn_checksum, validate_url, validate_article_record

# Explicitly define public module interfaces (Good software architecture practice)
__all__ = [
    "process_ml_rankings",
    "run_nepjol_scraper",
    "CacheManager",
    "CheckpointManager",
    "ScraperConfig",
    "CONFIG",
    "NetworkSession",
    "RateLimiter",
    "RobotsChecker",
    "validate_issn_checksum",
    "validate_url",
    "validate_article_record",
]
