#!/bin/bash
export PATH="/Users/jalalchowdhury/Library/Python/3.9/bin:$PATH"
cd "/Users/jalalchowdhury/PycharmProjects/Reddit Scraping"

echo "Closing old dashboard..."
pkill -f "streamlit" 

echo "Running scraper..."
python3 scraper_main.py dataisbeautiful --mode history --limit 20

echo "Starting dashboard..."
streamlit run dashboard.py
