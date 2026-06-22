"""
Network layer with retry logic, rate limiting, and robots.txt support.
"""

import logging
import time
import random
import threading
from typing import Optional
from functools import wraps
import urllib.robotparser
import urllib.parse
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    wait_exponential,
    stop_after_attempt,
    retry_if_exception_type,
    retry_if_result,
)

logger = logging.getLogger(__name__)


class RateLimiter:
    """Thread-safe rate limiter with exponential backoff."""
    
    def __init__(self, base_delay: float = 1.5):
        self.base_delay = base_delay
        self.last_request_time = 0
        self.lock = threading.Lock()
    
    def wait(self, multiplier: float = 1.0):
        """Apply rate limiting delay."""
        with self.lock:
            elapsed = time.time() - self.last_request_time
            delay = self.base_delay * multiplier
            
            if elapsed < delay:
                sleep_time = delay - elapsed
                logger.debug(f"Rate limit: sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)
            
            self.last_request_time = time.time()


class RobotsChecker:
    """Respects robots.txt with caching."""
    
    def __init__(self, cache_expiry: timedelta = timedelta(hours=24)):
        self.cache = {}
        self.cache_expiry = cache_expiry
        self.lock = threading.Lock()
    
    def can_fetch(self, url: str, user_agent: str = "*") -> bool:
        """Check if URL can be fetched according to robots.txt."""
        try:
            parsed = urllib.parse.urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            
            with self.lock:
                # Check cache
                if base_url in self.cache:
                    cached_rp, cached_time = self.cache[base_url]
                    if datetime.now() - cached_time < self.cache_expiry:
                        return cached_rp.can_fetch(user_agent, url)
                
                # Fetch robots.txt
                rp = urllib.robotparser.RobotFileParser()
                rp.set_url(f"{base_url}/robots.txt")
                rp.read()
                
                self.cache[base_url] = (rp, datetime.now())
                return rp.can_fetch(user_agent, url)
        
        except Exception as e:
            logger.warning(f"robots.txt check failed for {url}: {e}. Proceeding anyway.")
            return True  # Permissive fallback


class NetworkSession:
    """Enhanced requests session with retry logic, rate limiting, and robots.txt support."""
    
    def __init__(
        self,
        config,
        user_agents: list = None,
        allowed_hostnames: set = None,
    ):
        self.config = config
        self.session = requests.Session()
        self.user_agents = user_agents or [
            f"NepJOLPoliteScraper/9.0 (mailto:{config.user_email}; Academic Data Aggregator)",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ]
        self.allowed_hostnames = allowed_hostnames or set()
        self.rate_limiter = RateLimiter(config.base_delay_seconds)
        self.robots_checker = RobotsChecker(config.robots_txt_cache_expiry)
        self.request_lock = threading.Lock()
    
    def _validate_url_safety(self, url: str) -> bool:
        """Validate URL against whitelist and robots.txt."""
        try:
            parsed = urllib.parse.urlparse(url)
            hostname = parsed.hostname
            
            # Check whitelist
            if hostname not in self.allowed_hostnames:
                logger.error(f"URL hostname {hostname} not in whitelist: {url}")
                return False
            
            # Check robots.txt
            if self.config.check_robots_txt:
                user_agent = self.user_agents[0].split('/')[0]
                if not self.robots_checker.can_fetch(url, user_agent):
                    logger.warning(f"robots.txt disallows fetching: {url}")
                    return False
            
            return True
        except Exception as e:
            logger.error(f"URL validation error for {url}: {e}")
            return False
    
    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
        reraise=True,
    )
    def _fetch_with_retry(self, url: str, headers: dict, timeout: int) -> requests.Response:
        """Fetch URL with exponential backoff retry."""
        response = self.session.get(url, headers=headers, timeout=timeout)
        
        # Handle rate limiting
        if response.status_code in [429, 503]:
            logger.warning(f"Rate limited (HTTP {response.status_code}). Cooling down...")
            time.sleep(self.config.rate_limit_cooldown_seconds)
            raise requests.RequestException(f"Rate limited: HTTP {response.status_code}")
        
        response.raise_for_status()
        return response
    
    def get_html(
        self,
        url: str,
        is_nepjol: bool = True,
        timeout: Optional[int] = None,
    ) -> Optional[str]:
        """
        Fetch HTML with safety checks, rate limiting, and retries.
        
        Args:
            url: URL to fetch
            is_nepjol: Whether to apply NEPJOL-specific delays
            timeout: Request timeout in seconds
            
        Returns:
            HTML content as string, or None if fetch failed
        """
        if not self._validate_url_safety(url):
            return None
        
        timeout = timeout or self.config.request_timeout_seconds
        
        with self.request_lock:
            if is_nepjol:
                self.rate_limiter.wait(multiplier=1.0)
            else:
                time.sleep(self.config.crossref_delay_seconds)
        
        try:
            headers = {
                'User-Agent': random.choice(self.user_agents),
                'Accept': 'text/html,application/xhtml+xml',
                'Accept-Encoding': 'gzip, deflate',
            }
            
            response = self._fetch_with_retry(url, headers, timeout)
            logger.debug(f"Successfully fetched: {url}")
            return response.text
        
        except Exception as e:
            logger.error(f"Failed to fetch {url} after retries: {e}")
            return None


def create_soup(html: Optional[str]) -> Optional[BeautifulSoup]:
    """Parse HTML into BeautifulSoup object."""
    if not html:
        return None
    return BeautifulSoup(html, "html.parser")
