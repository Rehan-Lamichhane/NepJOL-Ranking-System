# core/scraper.py
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
import random
import re
import json
import os
import logging
import urllib.parse
import urllib.robotparser

from NepJOL_Ranking_System.Core.cache import CacheManager, CheckpointManager
from NepJOL_Ranking_System.Core.config import CONFIG

# Configure basic logging for the scraper
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

# =====================================================================
# SYSTEM REGISTRY ENDPOINTS & CACHE PARAMETERS
# =====================================================================
NEPJOL_URL = CONFIG.nepjol_url
JPPS_URL = CONFIG.jpps_url
CACHE_FILE = CONFIG.cache_file
CHECKPOINT_FILE = CONFIG.checkpoint_file

# Polite contact signature for the CrossRef API high-tier routing pool
USER_EMAIL = CONFIG.user_email

# Server Throttling Config
BASE_DELAY = CONFIG.base_delay_seconds
CROSSREF_DELAY = CONFIG.crossref_delay_seconds

USER_AGENTS = [
    f"NepJOLPoliteScraper/8.0 (mailto:{USER_EMAIL}; Academic Data Aggregator Bot)",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
]

session = requests.Session()

# Allowed hostnames for external requests (prevents SSRF to arbitrary hosts)
ALLOWED_HOSTNAMES = CONFIG.allowed_hostnames

# =====================================================================
# CACHE CONTROLLER ENGINE
# =====================================================================
MAX_CACHE_BYTES = 10 * 1024 * 1024  # 10 MB cache limit

# Initialize cache and checkpoint managers
cache_manager = CacheManager(CACHE_FILE)
checkpoint_manager = CheckpointManager(CHECKPOINT_FILE)

def load_local_cache():
    """Loads localized scraper cache if file footprint exists."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load cache file: %s", e)
            return {}
    return {}


def _prune_cache(cache_map):
    """Prunes cache if it grows too large (simple oldest-entry removal)."""
    try:
        # approximate size by JSON length
        s = json.dumps(cache_map)
        if len(s.encode('utf-8')) > MAX_CACHE_BYTES:
            # remove half of entries
            keys = list(cache_map.keys())
            for k in keys[:len(keys)//2]:
                cache_map.pop(k, None)
    except Exception:
        pass
    return cache_map


def save_local_cache(cache_data):
    """Commits volatile data strings to permanent local storage state."""
    try:
        cache_data = _prune_cache(cache_data)
        tmp = CACHE_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=4)
        os.replace(tmp, CACHE_FILE)
        try:
            os.chmod(CACHE_FILE, 0o600)
        except Exception:
            pass
    except Exception as e:
        logger.warning("   [Cache Error] Failed to write cache to disk: %s", e)

# Load the cache database instantly at runtime initialize
local_html_cache = load_local_cache()

# Basic robots.txt parser caching
_robot_parser = None

def _get_robot_parser(base_url=NEPJOL_URL):
    global _robot_parser
    if _robot_parser is None:
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.set_url(urllib.parse.urljoin(base_url, '/robots.txt'))
            rp.read()
            _robot_parser = rp
        except Exception:
            _robot_parser = None
    return _robot_parser


def _is_allowed_by_robots(url):
    rp = _get_robot_parser(NEPJOL_URL)
    if not rp:
        return True
    try:
        return rp.can_fetch(USER_AGENTS[0], url)
    except Exception:
        return True


def _is_hostname_allowed(url):
    try:
        host = urllib.parse.urlparse(url).hostname
        return host in ALLOWED_HOSTNAMES
    except Exception:
        return False


def get_soup_with_cache(url, is_nepjol=True, force_refresh=False):
    """
    Fetches raw HTML pages. Checks the local JSON cache file first.
    Only executes live requests if missing, obeying strict rate limits.
    """
    # Normalize URL
    parsed = urllib.parse.urljoin(NEPJOL_URL, url)

    if not _is_hostname_allowed(parsed):
        logger.warning("Blocked request to disallowed hostname: %s", parsed)
        return None

    if not force_refresh and parsed in local_html_cache:
        return BeautifulSoup(local_html_cache[parsed], "html.parser")

    # Respect robots
    if not _is_allowed_by_robots(parsed):
        logger.info("Robots.txt disallows fetching %s", parsed)
        return None

    # Enforce proactive server-friendly cooling periods on live cache misses
    if is_nepjol:
        time.sleep(BASE_DELAY + random.uniform(0.5, 1.5))
    else:
        time.sleep(CROSSREF_DELAY)

    try:
        headers = {
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Connection': 'keep-alive'
        }
        
        response = session.get(parsed, headers=headers, timeout=20)
        
        if response.status_code in [429, 503, 504]:
            logger.warning("   [Server Backoff] Status %s. Backing off for 15s...", response.status_code)
            time.sleep(15)
            response = session.get(parsed, headers=headers, timeout=25)
            
        response.raise_for_status()
        
        # Save structural source text response directly into cache system registry map
        if is_nepjol: # Only save bulky structural pages to avoid freezing storage arrays
            local_html_cache[parsed] = response.text
            save_local_cache(local_html_cache)
            
        return BeautifulSoup(response.text, "html.parser")
        
    except requests.RequestException as e:
        logger.warning("   [Network Log] Skipped node. Communications failed for %s: %s", parsed, e)
        return None

# =====================================================================
# ALGORITHMIC UTILITIES
# =====================================================================

def validate_issn_checksum(issn_str):
    """Validates an ISSN using the official ISO 3297 Modulo 11 check-digit algorithm."""
    if not issn_str or issn_str == "N/A":
        return False
    clean_issn = re.sub(r'[^0-9X]', '', issn_str.upper())
    if len(clean_issn) != 8:
        return False
    total = sum(int(clean_issn[i]) * (8 - i) for i in range(7))
    last_char = clean_issn[7]
    check_digit = 10 if last_char == 'X' else int(last_char)
    return (total + check_digit) % 11 == 0


def _is_valid_doi(doi_string):
    if not doi_string or doi_string == "N/A":
        return False
    doi = doi_string.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()
    # Very simple DOI pattern check
    pattern = re.compile(r'^10\.[\d]{4,9}/[-._;()/:A-Za-z0-9]+$')
    return bool(pattern.match(doi))


def get_crossref_citations(doi_string):
    """Queries the free CrossRef Open REST API endpoint safely using the article DOI."""
    if not _is_valid_doi(doi_string):
        return 0
    raw_doi = doi_string.replace("https://doi.org/", "").replace("http://doi.org/", "").strip()
    crossref_api_url = f"https://api.crossref.org/works/{raw_doi}"
    
    soup_api = get_soup_with_cache(crossref_api_url, is_nepjol=False)
    if soup_api and hasattr(soup_api, 'text'):
        try:
            import json as json_parse
            json_payload = json_parse.loads(soup_api.text)
            return int(json_payload.get("message", {}).get("is-referenced-by-count", 0))
        except Exception:
            pass
    return 0


def parse_frequency_to_numeric(frequency_string):
    """Translates natural text frequency expressions into an exact integer metric."""
    if not frequency_string:
        return 0
    text_lower = frequency_string.lower().strip()
    if "biannual" in text_lower or "semi-annual" in text_lower or "twice a year" in text_lower:
        return 2
    elif "annual" in text_lower or "once a year" in text_lower:
        return 1
    elif "tri-annual" in text_lower or "thrice a year" in text_lower:
        return 3
    elif "quarterly" in text_lower or "four times" in text_lower:
        return 4
    elif "bi-monthly" in text_lower:
        return 6
    elif "monthly" in text_lower:
        return 12
    digits = re.findall(r'(\d+)\s*(?:times|issues|per year|a year)', text_lower)
    return int(digits[0]) if digits else 0

# =====================================================================
# SYSTEM EXECUTION METHOD
# =====================================================================
def run_master_scraper():
    # --- Step 1: Querying and Localizing external JPPS Registry ---
    logger.info("--- Step 1: Querying and Localizing external JPPS Registry ---")
    jpps_dictionary = {}
    jpps_soup = get_soup_with_cache(JPPS_URL, is_nepjol=False)

    if jpps_soup:
        rows = jpps_soup.find_all("tr")
        for row in rows[1:]:
            cells = row.find_all("td")
            if len(cells) >= 4:
                raw_name = cells[1].get_text(strip=True)
                if raw_name:
                    jpps_dictionary[raw_name.lower().strip()] = {
                        "rating": cells[2].get_text(strip=True),
                        "last_assessed": cells[3].get_text(strip=True)
                    }
    logger.info("Successfully cached %s records. Moving to core pipeline...\n", len(jpps_dictionary))

    # --- Step 2: NepJOL Pipeline Run with Engine Intelligent Hook Caching ---
    logger.info("--- Step 2: Extracting NepJOL Journals (Polite Caching Active) ---")
    home_soup = get_soup_with_cache(NEPJOL_URL)
    master_dataset = []

    if home_soup:
        journal_links = home_soup.select("h3 a[href]")
        logger.info("Discovered %s total target entries across the root platform portal.", len(journal_links))
        
        for journal in journal_links:
            nepjol_name = journal.get_text(strip=True)
            journal_url = journal.get("href")
            if journal_url and journal_url.startswith("/"):
                journal_url = requests.compat.urljoin(NEPJOL_URL, journal_url)

            logger.info("\n[Processing Journal]: %s", nepjol_name)
            
            # Check if journal already processed in checkpoint
            if checkpoint_manager.has_journal(nepjol_name):
                logger.info(f"[CHECKPOINT] Journal '{nepjol_name}' already processed. Skipping...")
                existing_records = checkpoint_manager.get_journal(nepjol_name)
                if existing_records:
                    master_dataset.extend(existing_records)
                continue
            
            journal_soup = get_soup_with_cache(journal_url)
            if not journal_soup:
                continue

            # SUB-FLOW ROUTE: FOR AUTHORS -> ABOUT LINK -> FREQUENCY
            raw_frequency_text = ""
            info_block = journal_soup.select_one("div.pkp_block.block_information")
            if info_block:
                author_link = info_block.find("a", string=lambda text: text and "Authors" in text)
                if author_link:
                    author_url = requests.compat.urljoin(NEPJOL_URL, author_link.get("href"))
                    author_soup = get_soup_with_cache(author_url)
                    
                    if author_soup:
                        about_link = author_soup.select_one("ul.menu a[href*='/about'], nav a[href*='/about']")
                        if about_link:
                            about_url = requests.compat.urljoin(NEPJOL_URL, about_link.get("href"))
                        else:
                            about_url = author_url.split("/information/")[0] + "/about/editorialPolicies#publicationFrequency"
                        
                        about_soup = get_soup_with_cache(about_url)
                        if about_soup:
                            freq_header = about_soup.find(id="publicationFrequency")
                            if freq_header and freq_header.find_next("p"):
                                raw_frequency_text = freq_header.find_next("p").get_text(strip=True)

            stated_num_frequency = parse_frequency_to_numeric(raw_frequency_text)

            # Standard Core Extraction Fields
            issn_tag = journal_soup.select_one("div.pkp_footer_content p")
            issn_text = issn_tag.get_text(strip=True) if issn_tag else ""
            journal_issn = issn_text.split("ISSN")[1].strip().split()[0] if "ISSN" in issn_text else "N/A"
            
            formatted_issn = journal_issn
            if journal_issn != "N/A" and "-" not in journal_issn and len(journal_issn) == 8:
                formatted_issn = f"{journal_issn[:4]}-{journal_issn[4:]}"

            is_issn_valid = validate_issn_checksum(formatted_issn)
            issn_portal_link = f"https://portal.issn.org/resource/ISSN/{formatted_issn}" if formatted_issn != "N/A" else "N/A"

            jpps_lookup_key = nepjol_name.lower().strip()
            jpps_match = jpps_dictionary.get(jpps_lookup_key, {"rating": "New Title", "last_assessed": "N/A"})

            # SUB-FLOW ROUTE: CLICK "VIEW ISSUES" (a.read_more)
            archive_link_tag = journal_soup.select_one("a.read_more")
            if not archive_link_tag:
                continue
                
            archive_url = requests.compat.urljoin(NEPJOL_URL, archive_link_tag.get("href"))
            archive_soup = get_soup_with_cache(archive_url)
            if not archive_soup:
                continue
                
            issue_blocks = archive_soup.select("ul.issues_archive li div.obj_issue_summary")
            if not issue_blocks:
                issue_blocks = archive_soup.select("div.issue-summary, a.title")
            
            journal_articles = []  # Track articles for this journal
            for block in issue_blocks:
                issue_title_anchor = block.find("a", class_="title") if block.name != 'a' else block
                if not issue_title_anchor:
                    continue
                    
                volume_issue_text = issue_title_anchor.get_text(strip=True)
                issue_page_url = requests.compat.urljoin(NEPJOL_URL, issue_title_anchor.get("href"))
                
                issue_soup = get_soup_with_cache(issue_page_url)
                if not issue_soup:
                    continue
                    
                date_tag = issue_soup.select_one("div.published span.value")
                published_date = date_tag.get_text(strip=True) if date_tag else "N/A"
                
                articles = issue_soup.select("h4.title a[href]")
                for article in articles:
                    article_title = article.get_text(strip=True)
                    article_url = requests.compat.urljoin(NEPJOL_URL, article.get("href"))
                        
                    article_each_soup = get_soup_with_cache(article_url)
                    doi_url, article_views, article_downloads = "N/A", "0", "0"

                    if article_each_soup:
                        doi_tag = article_each_soup.select_one("section.item.doi span.value a")
                        if doi_tag:
                            doi_url = doi_tag["href"] if doi_tag.has_attr("href") else doi_tag.get_text(strip=True)

                        views_tag = article_each_soup.select("div.jolDownloadNumber")
                        if len(views_tag) >= 2:
                            try:
                                article_views = views_tag[0].find_all("div")[1].get_text(strip=True)
                                article_downloads = views_tag[1].find_all("div")[2].get_text(strip=True)
                            except IndexError:
                                pass 

                    article_citations = get_crossref_citations(doi_url)
                    
                    article_record = {
                        "Journal Name": nepjol_name,
                        "ISSN": formatted_issn,
                        "ISSN Structurally Valid": is_issn_valid,
                        "ISSN Portal Verification Link": issn_portal_link,
                        "Published Date": published_date,
                        "Volume/Issue": volume_issue_text,
                        "Article Title": article_title,
                        "Article URL": article_url,
                        "DOI": doi_url,
                        "Views": article_views,
                        "Downloads": article_downloads,
                        "Citations": article_citations,
                        "Stated Frequency Num": stated_num_frequency,
                        "JPPS Rating": jpps_match["rating"],
                        "JPPS Last Assessed": jpps_match["last_assessed"]
                    }
                    
                    journal_articles.append(article_record)
                    master_dataset.append(article_record)
            
            # Save checkpoint for this journal
            if journal_articles:
                checkpoint_manager.save_journal(nepjol_name, journal_articles)

    # --- Step 3: Data Structuring and Multi-CSV Exports to data/ folder ---
    logger.info("\n--- Step 3: Compiling Final Data Structuring & Multi-CSV Exports ---")
    df_all = pd.DataFrame(master_dataset)

    if not df_all.empty:
        df_all['Views'] = pd.to_numeric(df_all['Views'].astype(str).str.replace(',', ''), errors='coerce').fillna(0).astype(int)
        df_all['Downloads'] = pd.to_numeric(df_all['Downloads'].astype(str).str.replace(',', ''), errors='coerce').fillna(0).astype(int)
        df_all['Citations'] = df_all['Citations'].fillna(0).astype(int)

        df_all['Year'] = pd.to_datetime(df_all['Published Date'], errors='coerce').dt.year
        df_all['Year'] = df_all['Year'].fillna(df_all['Published Date'].astype(str).str.extract(r'(\d{4})')[0]).fillna(2026).astype(int)

        # CRITICAL LAYER: Establish data/ workspace folder safely before writing file streams
        os.makedirs("data", exist_ok=True)

        # 1. Output File: Time series Production Track Matrix
        issues_per_year_df = df_all.groupby(['Journal Name', 'Year'])['Volume/Issue'].nunique().reset_index()
        issues_per_year_df.columns = ['Journal Name', 'Year', 'Issues Published This Year']
        issues_per_year_df = issues_per_year_df.sort_values(by=["Journal Name", "Year"], ascending=[True, False])
        issues_per_year_df.to_csv(os.path.join("data", "journal_issues_per_year.csv"), index=False)

        avg_yearly_issues = issues_per_year_df.groupby('Journal Name')['Issues Published This Year'].mean().round(2).reset_index()
        avg_yearly_issues.columns = ['Journal Name', 'Calculated Avg Issues/Year']
        
        total_lifecycle_issues = issues_per_year_df.groupby('Journal Name')['Issues Published This Year'].sum().reset_index()
        total_lifecycle_issues.columns = ['Journal Name', 'Total_Issues Published']

        # 2. Output File: Articles Metadata
        df_articles = df_all[["Journal Name", "Article Title", "Article URL", "DOI", "Views", "Downloads", "Citations"]]
        df_articles = df_articles.sort_values(by="Journal Name", ascending=True, key=lambda col: col.str.strip().str.lower())
        df_articles.to_csv(os.path.join("data", "articles_metadata.csv"), index=False)

        # 3. Output File: Journals Aggregated Registry Data Summary Sheet
        journal_stats = df_all.groupby('Journal Name').agg(
            Total_Articles=('Article Title', 'count'),
            Average_Views=('Views', 'mean'),
            Average_Downloads=('Downloads', 'mean'),
            Average_Citations=('Citations', 'mean')
        ).reset_index()
        journal_stats[['Average_Views', 'Average_Downloads', 'Average_Citations']] = journal_stats[['Average_Views', 'Average_Downloads', 'Average_Citations']].round(2)

        journal_info = df_all[[
            'Journal Name', 'ISSN', 'ISSN Structurally Valid', 'ISSN Portal Verification Link', 
            'Published Date', 'Volume/Issue', 'Stated Frequency Num', 'JPPS Rating', 'JPPS Last Assessed'
        ]].drop_duplicates(subset=['Journal Name'])
        
        df_journals = pd.merge(journal_info, journal_stats, on='Journal Name', how='left')
        df_journals = pd.merge(df_journals, avg_yearly_issues, on='Journal Name', how='left')
        df_journals = pd.merge(df_journals, total_lifecycle_issues, on='Journal Name', how='left')
        
        df_journals = df_journals[[
            "Journal Name", "ISSN", "ISSN Structurally Valid", "ISSN Portal Verification Link",
            "Published Date", "Volume/Issue", "Stated Frequency Num", "Calculated Avg Issues/Year", "Total_Issues Published",
            "JPPS Rating", "JPPS Last Assessed", "Total_Articles", "Average_Views", "Average_Downloads", "Average_Citations"
        ]]
        df_journals = df_journals.sort_values(by="Journal Name", ascending=True, key=lambda col: col.str.strip().str.lower())
        df_journals.to_csv(os.path.join("data", "journals_metadata.csv"), index=False)
        
        logger.info("\n========================================================================")
        logger.info("✅ [SUCCESS] All target outputs written directly to local /data folder:")
        logger.info("   -> data/journals_metadata.csv")
        logger.info("   -> data/articles_metadata.csv")
        logger.info("   -> data/journal_issues_per_year.csv")
        logger.info("📊 Checkpoint Statistics:")
        checkpoint_stats = checkpoint_manager.stats()
        logger.info(f"   -> Total Journals Processed: {checkpoint_stats['total_journals']}")
        logger.info(f"   -> Total Records Checkpointed: {checkpoint_stats['total_records']}")
        logger.info("========================================================================")
    else:
        logger.info("Pipeline Alert: No master dataset rows generated.")

# Backward-compatible alias for package export
run_nepjol_scraper = run_master_scraper

if __name__ == "__main__":
    run_master_scraper()
