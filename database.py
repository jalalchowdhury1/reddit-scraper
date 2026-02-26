"""
Database models for Reddit Daily Dashboard
Handles tracking of seen posts to avoid duplicates
"""
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, Boolean
from sqlalchemy.orm import declarative_base, sessionmaker, Session

import config

Base = declarative_base()


class RedditPost(Base):
    """Model for storing Reddit posts"""
    __tablename__ = "reddit_posts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(String(50), unique=True, nullable=False, index=True)  # Reddit post ID
    subreddit = Column(String(100), nullable=False)
    title = Column(Text, nullable=False)
    author = Column(String(100))
    url = Column(String(500), nullable=False)
    permalink = Column(String(500))
    score = Column(Integer, default=0)
    num_comments = Column(Integer, default=0)
    created_utc = Column(DateTime)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    
    # Sorting info
    time_filter = Column(String(20))  # 'month' or 'year'
    
    # Screenshot info
    screenshot_path = Column(String(500))
    
    # Post content (for text posts)
    selftext = Column(Text)
    
    # Media info
    is_image = Column(Boolean, default=False)
    image_url = Column(String(500))
    
    # Display settings
    is_shown = Column(Boolean, default=True)  # For dashboard visibility
    
    def __repr__(self):
        return f"<RedditPost(id={self.post_id}, subreddit={self.subreddit}, title={self.title[:30]}...)>"


class ScrapeHistory(Base):
    """Model for tracking scrape history"""
    __tablename__ = "scrape_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    scraped_at = Column(DateTime, default=datetime.utcnow)
    subreddit = Column(String(100))
    posts_found = Column(Integer, default=0)
    new_posts = Column(Integer, default=0)
    duplicates_skipped = Column(Integer, default=0)
    errors = Column(Text)
    
    def __repr__(self):
        return f"<ScrapeHistory(subreddit={self.subreddit}, scraped_at={self.scraped_at})>"


def get_engine():
    """Create and return database engine"""
    db_path = config.DATABASE_PATH
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    return engine


def init_db():
    """Initialize database and create tables"""
    engine = get_engine()
    Base.metadata.create_all(engine)
    return engine


def get_session() -> Session:
    """Create and return a new database session"""
    engine = get_engine()
    Session = sessionmaker(bind=engine)
    return Session()


def is_post_seen(post_id: str) -> bool:
    """Check if a post has already been seen"""
    session = get_session()
    try:
        existing = session.query(RedditPost).filter(
            RedditPost.post_id == post_id
        ).first()
        return existing is not None
    finally:
        session.close()


def add_post(post_data: dict) -> RedditPost:
    """Add a new post to the database"""
    session = get_session()
    try:
        post = RedditPost(**post_data)
        session.add(post)
        session.commit()
        session.refresh(post)
        return post
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


def get_all_posts(limit: Optional[int] = None, subreddit: Optional[str] = None) -> List[RedditPost]:
    """Get all posts, optionally filtered by subreddit"""
    session = get_session()
    try:
        query = session.query(RedditPost).filter(RedditPost.is_shown == True)
        
        if subreddit:
            query = query.filter(RedditPost.subreddit == subreddit)
        
        query = query.order_by(RedditPost.scraped_at.desc(), RedditPost.score.desc())
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
    finally:
        session.close()


def get_posts_by_time_filter(time_filter: str, limit: Optional[int] = None) -> List[RedditPost]:
    """Get posts sorted by specific time filter"""
    session = get_session()
    try:
        query = session.query(RedditPost).filter(
            RedditPost.is_shown == True,
            RedditPost.time_filter == time_filter
        ).order_by(RedditPost.score.desc())
        
        if limit:
            query = query.limit(limit)
        
        return query.all()
    finally:
        session.close()


def mark_post_hidden(post_id: str):
    """Hide a post from the dashboard"""
    session = get_session()
    try:
        post = session.query(RedditPost).filter(RedditPost.post_id == post_id).first()
        if post:
            post.is_shown = False
            session.commit()
    finally:
        session.close()


def add_scrape_history(subreddit: str, posts_found: int, new_posts: int, duplicates: int, errors: str = None):
    """Add a scrape history entry"""
    session = get_session()
    try:
        history = ScrapeHistory(
            subreddit=subreddit,
            posts_found=posts_found,
            new_posts=new_posts,
            duplicates_skipped=duplicates,
            errors=errors
        )
        session.add(history)
        session.commit()
    finally:
        session.close()


def get_stats() -> dict:
    """Get database statistics"""
    session = get_session()
    try:
        total_posts = session.query(RedditPost).count()
        monthly_posts = session.query(RedditPost).filter(RedditPost.time_filter == "month").count()
        yearly_posts = session.query(RedditPost).filter(RedditPost.time_filter == "year").count()
        
        last_scrape = session.query(ScrapeHistory).order_by(ScrapeHistory.scraped_at.desc()).first()
        
        return {
            "total_posts": total_posts,
            "monthly_posts": monthly_posts,
            "yearly_posts": yearly_posts,
            "last_scrape": last_scrape.scraped_at if last_scrape else None
        }
    finally:
        session.close()


# Initialize database on import
init_db()
