"""
Configuration Module — Reddit Daily Dashboard + Daily Star News Scraper
=========================================================================

This module centralizes ALL configuration for the dashboard system:
- Data directory paths
- Reddit subreddit lists
- Daily Star RSS feed URLs
- Keyword categories for article matching

IMPORTANT FOR LLMs:
- Do NOT edit DATA_DIR unless you know what you're doing
- SUBREDDITS: Add/remove Reddit sources here
- DAILYSTAR_FEEDS: Add/remove Daily Star RSS feeds here
- NEWS_CATEGORIES: Add/remove/modify keyword phrases here

This file is imported by: dashboard.py, scrape_top.py, scrape_dailystar.py
"""
import os
from pathlib import Path

# ============================================================================
# PROJECT PATHS
# ============================================================================
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
DATABASE_PATH = DATA_DIR / "reddit_daily.db"

# Create directories if they don't exist
DATA_DIR.mkdir(exist_ok=True)
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# ============================================================================
# REDDIT API CONFIGURATION
# ============================================================================
# Get these from: https://www.reddit.com/prefs/apps
# Create a "script" type app
REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT = os.getenv("REDDIT_USER_AGENT", "reddit-daily-dashboard v1.0")

# ============================================================================
# SCRAPESERV CONFIGURATION (OPTIONAL)
# ============================================================================
SCRAPESERV_URL = os.getenv("SCRAPESERV_URL", "http://localhost:5006")

# ============================================================================
# REDDIT SUBREDDITS (13 configured)
# ============================================================================
# These are scraped by scrape_top.py for monthly and yearly top posts
# Format: {"name": str (subreddit name), "display_name": str (human-readable)}
# Add more by appending to this list
SUBREDDITS = [
    {"name": "dataisbeautiful", "display_name": "Data Is Beautiful"},
    {"name": "todayilearned", "display_name": "Today I Learned"},
    {"name": "sobooksoc", "display_name": "So many books, so little time"},
    {"name": "Fitness", "display_name": "Fitness"},
    {"name": "getmotivated", "display_name": "Get Motivated!"},
    {"name": "UnethicalLifeProTips", "display_name": "Unethical Life Pro Tips"},
    {"name": "LifeProTips", "display_name": "Life Pro Tips"},
    {"name": "TrueReddit", "display_name": "TrueReddit"},
    {"name": "UpliftingNews", "display_name": "Uplifting News"},
    {"name": "lifehacks", "display_name": "Lifehacks"},
    {"name": "Productivity", "display_name": "Productivity"},
    {"name": "PersonalFinance", "display_name": "Personal Finance"},
    {"name": "explainlikeimfive", "display_name": "Explain Like I'm Five"},
]

# ============================================================================
# REDDIT SCRAPER SETTINGS
# ============================================================================
POSTS_PER_SUBREDDIT = 5  # Top 5 posts per subreddit per scrape
SORT_BY_MONTHLY = "month"  # Get top posts from this month
SORT_BY_YEARLY = "year"  # Get top posts from this year
TIME_FILTERS = ["month", "year"]  # Priority order for scraping

# ============================================================================
# REDDIT DASHBOARD SETTINGS
# ============================================================================
DASHBOARD_TITLE = "Reddit Daily 📊"
DASHBOARD_ICON = "📊"

# ============================================================================
# DAILY STAR NEWS CONFIGURATION
# ============================================================================

# RSS Feed URLs for Daily Star (thedailystar.net)
# These feeds return ~10 articles each, updated regularly
# Format: Full HTTPS URL to /rss.xml endpoint
# Add more by appending to this list
DAILYSTAR_FEEDS = [
    "https://www.thedailystar.net/business/rss.xml",
    "https://www.thedailystar.net/business/economy/rss.xml",
    "https://www.thedailystar.net/news/bangladesh/rss.xml",
    "https://www.thedailystar.net/opinion/rss.xml",
    "https://www.thedailystar.net/news/rss.xml",
]

# ============================================================================
# KEYWORD CATEGORIES FOR NEWS MATCHING
# ============================================================================
# Articles are matched via case-insensitive substring search
# If ANY keyword phrase appears in (title + description).lower(), article matches that category
# One article can match multiple categories → creates separate CSV rows
# Format: {"name": str, "badge_class": str, "keywords": [str, ...]}
# badge_class: CSS class for styling (defined in style.css)

NEWS_CATEGORIES = [
    {
        "name": "India-Bangladesh Relations",
        "badge_class": "news-cat-relations",
        "keywords": [
            # Bilateral relationship terms
            "india bangladesh", "bilateral relations", "bilateral ties",
            "bilateral relationship", "diplomatic relations", "diplomatic ties",
            "two-way relations", "two-way ties",
            "bangladesh india", "india and bangladesh", "bangladesh and india",
            "indo-bangladesh", "bangladesh-india", "india–bangladesh", "bangladesh–india",

            # Trade and commerce
            "trade agreement", "trade agreements", "trade pact", "trade pacts",
            "free trade agreement", "fta", "ftas",

            # Infrastructure and transit
            "transit corridor", "energy pipeline", "energy pipelines",
            "oil pipeline", "oil pipelines", "gas pipeline", "gas pipelines",
            "energy conduit", "river link", "river links", "river linking",
            "waterway link", "waterway links", "river connection", "river connections",
            "land port", "rail link", "road link", "bus service",
            "benapole railway station", "benapole rail link", "benapole rail", "benapole railways",

            # Agreements and treaties
            "visa agreement", "visa agreements", "visa pact", "visa pacts",
            "visa deal", "visa deals",
            "water sharing treaty", "water sharing treaties", "water sharing pact",
            "water sharing pacts", "water treaty",

            # Security and defense
            "border security", "border security measures", "border controls",
            "border control", "border protection", "border enforcement",
            "border guard", "border guards",
            "defence cooperation", "defense cooperation", "defence collaboration",
            "defense collaboration", "military cooperation", "military collaboration",
            "defence cooperation agreement", "defense cooperation agreement",
        ],
    },
    {
        "name": "Bangladesh Economy",
        "badge_class": "news-cat-economy",
        "keywords": [
            # Export and trade
            "export growth", "exports growth", "export expansion", "exports expansion",
            "growth in exports", "export volumes growth", "increase in exports",
            "garment sector", "garment industry", "textile export", "textile exports",
            "textiles export", "textiles exports", "textile export volumes", "export of textiles",
            "apparel sector", "apparel industry", "clothing sector", "clothing industry",
            "textile industry", "textiles industry", "textile industries", "textiles industries",

            # Investment and foreign capital
            "foreign direct investment", "fdi", "direct foreign investment",
            "foreign investment", "inward fdi",

            # Finance and currency
            "exchange rate", "exchange rates", "currency exchange rate",
            "currency rate", "fx rate", "forex rate", "exchange-rate",
            "fiscal deficit", "budget deficit", "fiscal shortfall",
            "budget shortfall", "fiscal gap",
            "interest rate", "interest rates", "borrowing rate", "lending rate",
            "cost of borrowing",

            # Monetary and banking
            "monetary policy", "monetary policies", "central bank policy",
            "central bank policies", "central bank", "central banks",
            "reserve bank", "monetary authority", "banking sector", "banking industry",
            "banks sector", "financial sector",

            # Economic growth
            "gdp growth", "gross domestic product growth", "gdp expansion",
            "economic growth",

            # Remittances
            "remittance inflow", "remittance inflows", "remittance receipts",
            "inflows of remittances", "worker remittances", "remittance income",

            # Stock market and equity
            "stock market", "stock markets", "share market", "share price",
            "share prices", "stock price", "stock prices",
            "equity market", "equity price", "equity prices", "capital market",

            # Inflation and pricing
            "inflation rate", "inflation rates", "rate of inflation", "price inflation",

            # Agriculture and business sectors
            "agribusiness sector", "agribusiness", "agricultural business sector",
            "agricultural sector", "agri-business sector",

            # Government finance
            "budget proposal", "budget proposals", "budget plan",
            "fiscal proposal", "budget draft",
            "tax revenue", "tax revenues", "tax receipts", "tax collection",
            "tax collections",

            # Manufacturing and production
            "manufacturing output", "manufacturing production", "manufacturing outputs",
            "industrial output",

            # Debt and interest
            "interest payments", "interest payment", "interest expenses",
            "interest expense", "interest paid", "debt service", "debt servicing",
        ],
    },
    {
        "name": "Good News",
        "badge_class": "news-cat-goodnews",
        "keywords": [
            # Success and achievements
            "success story", "success stories", "achievement story",
            "success narrative", "case study", "case studies",
            "success example", "success examples",
            "record achievement", "record achievements", "record-breaking achievement",
            "record-breaking achievements", "milestone achievement",
            "record feat", "record feats",

            # Inauguration and launches
            "inaugurated today", "inaugurated", "officially inaugurated",
            "opened today", "inaugurated this morning", "inaugurated this afternoon",
            "launching new", "unveiled new", "debuted new", "introduced new",
            "launched the new",

            # Funding and support
            "funded by", "funded through", "financed by", "backed by",
            "supported by", "sponsored by",

            # Donations and fundraising
            "donation drive", "donation drives", "donation campaign",
            "fundraising drive", "fundraising campaign", "charity drive",
            "charity campaign", "donation fundraiser", "fundraising event",

            # Emergency and rescue
            "rescue operation", "rescue operations", "rescue mission",
            "search and rescue operation", "emergency rescue operation",
            "rescue efforts", "evacuation operation",

            # Medical and health breakthroughs
            "medical breakthrough", "medical breakthroughs", "healthcare breakthrough",
            "scientific breakthrough", "medical advance", "medical advances",
            "health breakthrough",

            # Education
            "education initiative", "education initiatives", "learning initiative",
            "education program", "education programs",

            # Vaccination and health campaigns
            "vaccination campaign", "vaccination campaigns", "vaccination drive",
            "immunization campaign", "immunisation campaign",
            "immunization drive", "immunisation drive",
            "vaccination program", "immunization program", "immunisation program",

            # Community development
            "community uplift", "community upliftment", "community empowerment",
            "community development", "community advancement", "community uplift initiatives",

            # Peace and agreements
            "peace accord", "peace accords", "peace agreement", "peace agreements",
            "peace treaty", "peace treaties", "peace pact", "peace pacts",

            # Events and celebrations
            "celebration held", "celebration conducted", "event held",
            "festivity held", "celebration took place", "celebration organised",
            "celebration organized",

            # Technology and innovation
            "technology startup", "tech startup", "technology startups",
            "tech startups", "startup technology company", "startup",
            "innovation hub", "innovation hubs", "innovation centre",
            "innovation center", "innovation centers", "innovation park",
            "innovation parks",

            # Sports and culture
            "sports championship", "cultural festival", "cultural festivals",
            "cultural event", "arts festival", "culture festival",
            "heritage festival", "cultural celebrations",
        ],
    },
]

# ============================================================================
# SCRAPER SETTINGS (Advanced)
# ============================================================================
# These are used by scrape_dailystar.py
SCRAPER_TIMEOUT = 30  # seconds
SCRAPER_DELAY = 1.5  # seconds between feed requests
SCRAPER_USER_AGENT = "DailyStarNewsScraper/1.0"
