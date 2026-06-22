"""
Cache and checkpoint management with thread safety.
Persistent state for resume capability.
"""

import json
import os
import logging
import threading
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class CacheManager:
    """Thread-safe cache manager with atomic writes."""
    
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self.data: Dict[str, Any] = self._load()
        self.lock = threading.Lock()
    
    def _load(self) -> Dict[str, Any]:
        """Load cache from disk."""
        if not os.path.exists(self.cache_file):
            return {}
        
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading cache from {self.cache_file}: {e}")
            return {}
    
    def _save(self):
        """Atomically save cache to disk using temp file."""
        try:
            temp_file = self.cache_file + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
            os.replace(temp_file, self.cache_file)
            logger.debug(f"Cache saved to {self.cache_file}")
        except Exception as e:
            logger.error(f"Error saving cache: {e}")
            # Attempt cleanup
            try:
                os.remove(temp_file)
            except:
                pass
    
    def get(self, key: str, default=None) -> Any:
        """Get value from cache."""
        with self.lock:
            return self.data.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set value in cache and persist."""
        with self.lock:
            self.data[key] = value
            self._save()
    
    def exists(self, key: str) -> bool:
        """Check if key exists in cache."""
        with self.lock:
            return key in self.data
    
    def clear(self):
        """Clear all cache."""
        with self.lock:
            self.data.clear()
            self._save()


class CheckpointManager:
    """
    Manages permanent checkpoints for resumable scraping.
    Tracks completed journals and their records.
    """
    
    def __init__(self, checkpoint_file: str):
        self.checkpoint_file = checkpoint_file
        self.data: Dict[str, List[Dict[str, Any]]] = self._load()
        self.lock = threading.Lock()
    
    def _load(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load checkpoint data from disk."""
        if not os.path.exists(self.checkpoint_file):
            return {}
        
        try:
            with open(self.checkpoint_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading checkpoint from {self.checkpoint_file}: {e}")
            return {}
    
    def _save(self):
        """Atomically save checkpoint to disk."""
        try:
            temp_file = self.checkpoint_file + '.tmp'
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=4)
            os.replace(temp_file, self.checkpoint_file)
            logger.info(f"💾 Checkpoint saved: {self.checkpoint_file}")
        except Exception as e:
            logger.error(f"Error saving checkpoint: {e}")
            try:
                os.remove(temp_file)
            except:
                pass
    
    def get_journal(self, journal_name: str) -> Optional[List[Dict[str, Any]]]:
        """Retrieve completed records for a journal."""
        with self.lock:
            return self.data.get(journal_name)
    
    def has_journal(self, journal_name: str) -> bool:
        """Check if journal has been processed."""
        with self.lock:
            return journal_name in self.data
    
    def save_journal(self, journal_name: str, records: List[Dict[str, Any]]):
        """Save completed records for a journal."""
        with self.lock:
            self.data[journal_name] = records
            self._save()
            logger.info(f"Checkpoint saved for: {journal_name} ({len(records)} records)")
    
    def get_all_journals(self) -> List[str]:
        """Get list of completed journals."""
        with self.lock:
            return list(self.data.keys())
    
    def stats(self) -> Dict[str, Any]:
        """Get checkpoint statistics."""
        with self.lock:
            total_journals = len(self.data)
            total_records = sum(len(records) for records in self.data.values())
            return {
                "total_journals": total_journals,
                "total_records": total_records,
                "journals": list(self.data.keys()),
            }
