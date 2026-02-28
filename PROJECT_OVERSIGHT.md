# Reddit & News Dashboard: System Oversight

## 1. Project Architecture
- **Backend**: Python 3.9 / FastAPI (`server.py`) reads from CSV.
- **Data Strategy**: CSV-based storage in `/data`. No SQL database.
- **Automation**: GitHub Actions (`.github/workflows/daily_scrape.yml`) runs the core scrapers.

## 2. Core Scrapers (/core)
1. **scrape_top.py**: Triple-redundant Reddit scraper (JSON -> HTML -> RSS). 
2. **scrape_ritholtz.py**: Fetches 10 financial articles daily.
3. **scrape_googlenews.py**: Filtered RSS aggregator for Bangladesh-specific news.

## 3. Data Flow
Scrapers save to `/data` -> `server.py` reads `/data` -> Jinja2 templates render the dashboard.
