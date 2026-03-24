import html
import re
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import glob
import logging

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI()
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def clean_text(text) -> str:
    if pd.isna(text) or not text: return ""
    return html.unescape(str(text))

def format_score(score: int) -> str:
    """Format large scores with 'k' suffix (e.g., 82450 -> 82.4k)"""
    if score >= 1000:
        return f"{score / 1000:.1f}k"
    return str(score)

def calculate_reading_time(text: str) -> int:
    """Calculate estimated reading time in minutes based on word count."""
    if not text:
        return 0
    word_count = len(text.strip().split())
    reading_time = max(1, round(word_count / 200))  # ~200 words per minute
    return reading_time

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")

@app.get("/api/data")
def get_data():
    data = {"monthly": [], "yearly": [], "news": [], "ritholtz": []}
    
    # Load Reddit
    posts_files = glob.glob(str(BASE_DIR / "data/r_*/posts.csv"))
    if posts_files:
        dfs = []
        for f in posts_files:
            if "_yearly" in f: continue
            try:
                df = pd.read_csv(f)
                if df.empty or "id" not in df.columns: continue
                df['subreddit'] = Path(f).parent.name.replace('r_', '')
                df['time_filter'] = 'monthly'
                dfs.append(df)
            except: pass
            
        yearly_files = glob.glob(str(BASE_DIR / "data/r_*_yearly/posts.csv"))
        for f in yearly_files:
            try:
                df = pd.read_csv(f)
                if df.empty or "id" not in df.columns: continue
                df['subreddit'] = Path(f).parent.name.replace('r_', '').replace('_yearly', '')
                df['time_filter'] = 'yearly'
                dfs.append(df)
            except: pass

        if dfs:
            combined = pd.concat(dfs, ignore_index=True).fillna("")
            combined['id'] = combined['id'].astype(str)
            combined = combined.drop_duplicates(subset=["id", "time_filter"], keep="first")
            combined['score'] = pd.to_numeric(combined['score'], errors='coerce').fillna(0).astype(int)
            combined = combined.sort_values("score", ascending=False)
            
            for _, row in combined.iterrows():
                pid = str(row['id']).strip()
                # Inside the Reddit loop in server.py:
                raw_url = f"https://www.reddit.com{row.get('permalink', '')}" if not str(row.get('permalink', '')).startswith('http') else row.get('permalink', '')
                # Safety check for double-prefixes
                clean_url = raw_url.replace("https://www.reddit.comhttps://", "https://")
                
                # Calculate reading time from selftext
                selftext = str(row.get('selftext', ''))
                read_time = calculate_reading_time(selftext)
                
                item = {
                    "id": pid, 
                    "title": clean_text(row['title']), 
                    "desc": clean_text(selftext[:300]),
                    "url": clean_url,
                    "meta": f"r/{row['subreddit']} • {row['time_filter'].upper()} • {format_score(row['score'])} pts • ⏱️ {read_time} min"
                }
                data[row['time_filter']].append(item)

    # Load Google News
    news_csv = BASE_DIR / "data/googlenews/articles.csv"
    if news_csv.exists():
        try:
            news_df = pd.read_csv(news_csv).fillna("")
            if not news_df.empty and "article_id" in news_df.columns:
                news_df = news_df.drop_duplicates(subset=["article_id", "category"], keep="first")
                news_df = news_df.sort_values("pub_date", ascending=False)
                for _, row in news_df.iterrows():
                    pid = f"gn_{row['article_id']}"
                    publisher = str(row.get('author', 'NEWS')).upper()
                    description = str(row.get('description', ''))
                    read_time = calculate_reading_time(description)
                    
                    data["news"].append({
                        "id": pid, 
                        "title": clean_text(row['title']), 
                        "desc": clean_text(description[:300]),
                        "url": str(row['url']).replace("http://", "https://"), 
                        "meta": f"{publisher} • {row.get('category', '').upper()} • {str(row.get('pub_date', ''))[:10]} • ⏱️ {read_time} min"
                    })
        except: pass

    # Load Ritholtz
    ritholtz_csv = BASE_DIR / "data/ritholtz/articles.csv"
    if ritholtz_csv.exists():
        try:
            rith_df = pd.read_csv(ritholtz_csv).fillna("")
            if not rith_df.empty and "article_id" in rith_df.columns:
                rith_df = rith_df.drop_duplicates(subset=["article_id"], keep="first")
                for _, row in rith_df.iterrows():
                    pid = f"rth_{row['article_id']}"
                    description = str(row.get('description', ''))
                    read_time = calculate_reading_time(description)
                    
                    data["ritholtz"].append({
                        "id": pid, 
                        "title": clean_text(row['title']), 
                        "desc": clean_text(description[:300]),
                        "url": row['url'], 
                        "meta": f"AM READS • {str(row.get('pub_date', ''))[:10]} • ⏱️ {read_time} min"
                    })
        except: pass

    # Load Read Trung (SatPost)
    trung_csv = BASE_DIR / "data/trung/articles.csv"
    if trung_csv.exists():
        try:
            trung_df = pd.read_csv(trung_csv).fillna("")
            if not trung_df.empty and "article_id" in trung_df.columns:
                trung_df = trung_df.drop_duplicates(subset=["article_id"], keep="first")
                for _, row in trung_df.iterrows():
                    pid = f"trg_{row['article_id']}"
                    description = str(row.get('description', ''))
                    read_time = calculate_reading_time(description)
                    
                    data["ritholtz"].append({
                        "id": pid, 
                        "title": clean_text(row['title']), 
                        "desc": clean_text(description[:300]),
                        "url": row['url'], 
                        "meta": f"SATPOST • {str(row.get('pub_date', ''))[:10]} • ⏱️ {read_time} min"
                    })
        except: pass

    # Chronological sort for the merged AM Reads tab
    def extract_date_from_meta(item):
        match = re.search(r'\d{4}-\d{2}-\d{2}', item.get('meta', ''))
        return match.group(0) if match else "1970-01-01"
        
    if "ritholtz" in data and data["ritholtz"]:
        data["ritholtz"].sort(key=extract_date_from_meta, reverse=True)

    for k in data: 
        data[k] = data[k][:50]
        
    return data
