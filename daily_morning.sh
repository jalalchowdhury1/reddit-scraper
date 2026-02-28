#!/bin/bash
# 1. Navigate to project
cd "/Users/jalalchowdhury/PycharmProjects/Reddit Scraping"

# 2. Activate virtual environment
source venv/bin/activate

# 3. Run all scrapers silently
echo "📡 Refreshing Reddit, AM Reads, and Google News..."
python3 scrape_top.py
python3 scrape_ritholtz.py
python3 scrape_googlenews.py

# 4. Open the browser automatically
open "http://localhost:8000"

# 5. Start the server
echo "🚀 Launching Dashboard..."
uvicorn server:app --reload --reload-exclude '.repo_clone/*'
