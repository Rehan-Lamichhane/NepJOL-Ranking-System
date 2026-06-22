"""
Configuration management for NepJOL scraper.
Externalize all tunable parameters and secrets.
"""

import os
from dataclasses import dataclass
from typing import Set
from datetime import timedelta


@dataclass
class ScraperConfig:
    """Centralized configuration for scraper parameters."""
    
    # URLs
    nepjol_url: str = "https://www.nepjol.info/"
    jpps_url: str = "https://www.journalquality.info/en/journals-all/?platform=nepjol"
    
    # Storage
    cache_file: str = "nepjol_scratch_cache.json"
    checkpoint_file: str = "nepjol_checkpoint_data.json"
    data_directory: str = "data"
    
    # Network behavior
    base_delay_seconds: float = 1.5
    crossref_delay_seconds: float = 0.3
    request_timeout_seconds: int = 20
    retry_timeout_seconds: int = 25
    
    # Retry strategy
    max_retries: int = 3
    initial_backoff_seconds: float = 2
    max_backoff_seconds: float = 30
    backoff_multiplier: float = 1.5
    rate_limit_cooldown_seconds: int = 10
    
    # Threading
    max_workers: int = 4
    thread_shutdown_timeout_seconds: int = 60
    
    # User agent
    user_email: str = os.getenv("USER_EMAIL", "your-email@example.com")
    
    # Robots.txt
    check_robots_txt: bool = True
    robots_txt_cache_expiry: timedelta = timedelta(hours=24)
    
    # Allowed hosts (whitelist)
    allowed_hostnames: Set[str] = None
    
    # Data quality
    min_issn_length: int = 8
    issn_validation_enabled: bool = True
    
    # Fuzzy matching
    fuzzy_match_threshold: float = 0.80
    
    # Logging
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    log_file: str = "scraper.log"
    log_format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    
    def __post_init__(self):
        """Initialize derived fields."""
        if self.allowed_hostnames is None:
            import urllib.parse
            nepjol_host = urllib.parse.urlparse(self.nepjol_url).hostname
            jpps_host = urllib.parse.urlparse(self.jpps_url).hostname
            self.allowed_hostnames = {nepjol_host, jpps_host, 'api.crossref.org'}
    
    @classmethod
    def from_env(cls) -> "ScraperConfig":
        """Load configuration from environment variables."""
        return cls(
            nepjol_url=os.getenv("NEPJOL_URL", cls.nepjol_url),
            jpps_url=os.getenv("JPPS_URL", cls.jpps_url),
            cache_file=os.getenv("CACHE_FILE", cls.cache_file),
            checkpoint_file=os.getenv("CHECKPOINT_FILE", cls.checkpoint_file),
            data_directory=os.getenv("DATA_DIR", cls.data_directory),
            base_delay_seconds=float(os.getenv("BASE_DELAY", cls.base_delay_seconds)),
            max_workers=int(os.getenv("MAX_WORKERS", cls.max_workers)),
            user_email=os.getenv("USER_EMAIL", cls.user_email),
        )


# Singleton config instance
CONFIG = ScraperConfig.from_env()
