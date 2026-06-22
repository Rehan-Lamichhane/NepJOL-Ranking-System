"""
Data validation utilities for scraper output.
Ensures data quality before DataFrame construction.
"""

import re
import logging
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class ValidationError(Exception):
    """Raised when data validation fails."""
    pass


def validate_issn_checksum(issn_str: str) -> bool:
    """
    Validate ISSN checksum using ISO 2108 standard.
    
    Args:
        issn_str: ISSN string in any format
        
    Returns:
        True if checksum is valid, False otherwise
    """
    if not issn_str or issn_str == "N/A":
        return False
    
    clean_issn = re.sub(r'[^0-9X]', '', issn_str.upper())
    
    if len(clean_issn) != 8:
        logger.debug(f"Invalid ISSN length: {issn_str} (cleaned: {clean_issn})")
        return False
    
    try:
        total = sum(int(clean_issn[i]) * (8 - i) for i in range(7))
        check_digit = 10 if clean_issn[7] == 'X' else int(clean_issn[7])
        is_valid = (total + check_digit) % 11 == 0
        
        if not is_valid:
            logger.debug(f"ISSN checksum mismatch for: {issn_str}")
        
        return is_valid
    except ValueError as e:
        logger.debug(f"Error validating ISSN {issn_str}: {e}")
        return False


def validate_url(url: str, allowed_hostnames: set) -> bool:
    """
    Validate that URL is from allowed hostnames (security whitelist).
    
    Args:
        url: URL to validate
        allowed_hostnames: Set of allowed hostnames
        
    Returns:
        True if URL's hostname is in whitelist
    """
    try:
        hostname = urlparse(url).hostname
        return hostname in allowed_hostnames
    except Exception as e:
        logger.warning(f"URL validation failed for {url}: {e}")
        return False


def validate_article_record(record: Dict[str, Any], required_fields: List[str] = None) -> bool:
    """
    Validate article record has required fields and valid structure.
    
    Args:
        record: Article metadata dictionary
        required_fields: List of field names that must be present
        
    Returns:
        True if record is valid
        
    Raises:
        ValidationError if validation fails
    """
    if required_fields is None:
        required_fields = [
            "Journal Name", "Article Title", "Article URL",
            "Published Date", "Volume/Issue"
        ]
    
    # Check required fields
    missing_fields = [f for f in required_fields if f not in record]
    if missing_fields:
        raise ValidationError(f"Missing required fields: {missing_fields} in record: {record}")
    
    # Validate non-empty strings
    for field in required_fields:
        if isinstance(record[field], str) and not record[field].strip():
            raise ValidationError(f"Empty string in required field '{field}'")
    
    # Validate URL format
    if not isinstance(record.get("Article URL"), str) or not record["Article URL"].startswith("http"):
        raise ValidationError(f"Invalid Article URL: {record.get('Article URL')}")
    
    return True


def validate_journal_record(record: Dict[str, Any]) -> bool:
    """
    Validate journal metadata record.
    
    Args:
        record: Journal metadata dictionary
        
    Returns:
        True if record is valid
        
    Raises:
        ValidationError if validation fails
    """
    required_fields = ["Journal Name", "ISSN"]
    
    missing_fields = [f for f in required_fields if f not in record]
    if missing_fields:
        raise ValidationError(f"Missing required fields in journal record: {missing_fields}")
    
    # Journal name should not be empty
    if not record["Journal Name"].strip():
        raise ValidationError("Journal name cannot be empty")
    
    return True


def sanitize_dataframe(df_data: List[Dict[str, Any]], record_type: str = "article") -> List[Dict[str, Any]]:
    """
    Sanitize and validate records before DataFrame construction.
    
    Args:
        df_data: List of record dictionaries
        record_type: Type of record ("article" or "journal")
        
    Returns:
        Cleaned list of records
        
    Raises:
        ValidationError if records are invalid
    """
    if not df_data:
        logger.warning("Empty dataset provided to sanitize_dataframe")
        return []
    
    validator = validate_article_record if record_type == "article" else validate_journal_record
    valid_records = []
    
    for idx, record in enumerate(df_data):
        try:
            validator(record)
            valid_records.append(record)
        except ValidationError as e:
            logger.error(f"Invalid record at index {idx}: {e}")
            # Continue processing other records instead of crashing
    
    if not valid_records:
        raise ValidationError(f"No valid {record_type} records after validation")
    
    if len(valid_records) < len(df_data):
        logger.warning(
            f"Filtered {len(df_data) - len(valid_records)} invalid records. "
            f"{len(valid_records)} records remaining."
        )
    
    return valid_records
