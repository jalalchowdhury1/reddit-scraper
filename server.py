import json
import os
import tempfile
import html
from pathlib import Path
import pandas as pd
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import glob

app = FastAPI()
templates = Jinja2Templates(directory="templates")

READ_FILE = Path("data/read_posts.json")
FAV_FILE = Path("data/favorite_posts.json")

def load_json_set(filepath: Path) -> set:
    if not filepath.exists(): return set()
    try:
        with open(filepath, "r") as f:
            return set(str(item).rsplit("_month", 1)[0].rsplit("_year", 1)[0] for item in json.load(f))
    except: return set()

def save_json_set(data_set: set, filepath: Path):
    filepath.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(filepath.parent), suffix=".tmp")
    with os.fdopen(fd, "w") as f: json.dump(sorted(list(data_set)), f, indent=2)
    os.replace(tmp, str(filepath))

def clean_text(text) -> str:
    if pd.isna(text) or not text: return ""
    return html.unescape(str(text))

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/api/data")
def get_data(show_read: bool = False):
    read_posts = load_json_set(READ_FILE)
    fav_posts = load_json_set(FAV_FILE)
    
    data = {"monthly": [], "yearly": [], "news": [], "ritholtz": []}
    
    # Load Reddit
    posts_files = glob.glob("data/r_*/posts.csv")
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
            
        yearly_files = glob.glob("data/r_*_yearly/posts.csv")
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
                if not show_read and pid in read_posts and pid not in fav_posts: continue
                
                item = {
                    "id": pid, 
                    "title": clean_text(row['title']), 
                    "desc": clean_text(str(row.get('selftext', ''))[:300]),
                    "url": f"https://www.reddit.com{row.get('permalink', '')}",
                    "meta": f"r/{row['subreddit']} • {row['time_filter'].upper()} • {row['score']:,} pts",
                    "is_read": pid in read_posts, "is_fav": pid in fav_posts
                }
                data[row['time_filter']].append(item)

    # Load Google News (Replaces Daily Star)
    if Path("data/googlenews/articles.csv").exists():
        try:
            news_df = pd.read_csv("data/googlenews/articles.csv").fillna("")
            if not news_df.empty and "article_id" in news_df.columns:
                news_df = news_df.drop_duplicates(subset=["article_id", "category"], keep="first")
                news_df = news_df.sort_values("pub_date", ascending=False)
                for _, row in news_df.iterrows():
                    pid = f"gn_{row['article_id']}"
                    if not show_read and pid in read_posts and pid not in fav_posts: continue
                    
                    # Premium formatting: Publisher Name • Category • Date
                    publisher = str(row.get('author', 'NEWS')).upper()
                    
                    data["news"].append({
                        "id": pid, 
                        "title": clean_text(row['title']), 
                        "desc": clean_text(str(row.get('description', ''))[:300]),
                        "url": str(row['url']).replace("http://", "https://"), 
                        "meta": f"{publisher} • {row.get('category', '').upper()} • {str(row.get('pub_date', ''))[:10]}",
                        "is_read": pid in read_posts, "is_fav": pid in fav_posts
                    })
        except: pass

    # Load Ritholtz
    if Path("data/ritholtz/articles.csv").exists():
        try:
            rith_df = pd.read_csv("data/ritholtz/articles.csv").fillna("")
            if not rith_df.empty and "article_id" in rith_df.columns:
                rith_df = rith_df.drop_duplicates(subset=["article_id"], keep="first")
                for _, row in rith_df.iterrows():
                    pid = f"rth_{row['article_id']}"
                    if not show_read and pid in read_posts and pid not in fav_posts: continue
                    data["ritholtz"].append({
                        "id": pid, 
                        "title": clean_text(row['title']), 
                        "desc": clean_text(str(row.get('description', ''))[:300]),
                        "url": row['url'], 
                        "meta": f"AM READS • {str(row.get('pub_date', ''))[:10]}",
                        "is_read": pid in read_posts, "is_fav": pid in fav_posts
                    })
        except: pass

    for k in data: data[k] = data[k][:50]
    return data

class ActionReq(BaseModel):
    id: str
    action: str 

@app.post("/api/toggle")
def toggle_item(req: ActionReq):
    filepath = READ_FILE if req.action == 'read' else FAV_FILE
    data_set = load_json_set(filepath)
    if req.id in data_set: data_set.remove(req.id)
    else: data_set.add(req.id)
    save_json_set(data_set, filepath)
    return {"status": "success", "is_active": req.id in data_set}
