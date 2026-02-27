#!/bin/bash

# Ensure PATH is set
export PATH="/Users/jalalchowdhury/Library/Python/3.9/bin:$PATH"

# Also add python3 to PATH if needed
export PATH="/Library/Developer/CommandLineTools/usr/bin:$PATH"

echo "🚀 Starting Reddit Scraper & Dashboard..."
echo ""

# Scrape data from subreddits
echo "📡 Scraping data..."
python3 scraper_main.py dataisbeautiful --mode history --limit 20
python3 scraper_main.py todayilearned --mode history --limit 20

echo ""
echo "✅ Scraping complete! Starting dashboard..."
echo ""

# Run the dashboard
streamlit run dashboard.py
