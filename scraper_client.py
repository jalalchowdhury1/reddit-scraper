"""
ScrapeServ Client Module
Takes screenshots of Reddit posts using the ScrapeServ API
"""
import os
import logging
import requests
from pathlib import Path
from typing import Optional
from io import BytesIO

import config

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ScrapeServClient:
    """Client for interacting with ScrapeServ API"""
    
    def __init__(self, base_url: str = None):
        """Initialize the ScrapeServ client"""
        self.base_url = base_url or config.SCRAPESERV_URL
        self.screenshots_dir = config.SCREENSHOTS_DIR
    
    def is_server_running(self) -> bool:
        """Check if ScrapeServ is running"""
        try:
            response = requests.get(self.base_url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False
    
    def scrape_url(self, url: str, wait: int = 1500, max_screenshots: int = 3) -> dict:
        """
        Scrape a URL and get screenshots
        
        Args:
            url: URL to scrape
            wait: Milliseconds to wait after scrolling
            max_screenshots: Maximum number of screenshots
            
        Returns:
            Dictionary with metadata and screenshot paths
        """
        endpoint = f"{self.base_url}/scrape"
        
        payload = {
            "url": url,
            "wait": wait,
            "max_screenshots": max_screenshots
        }
        
        try:
            logger.info(f"Scraping URL: {url}")
            response = requests.post(endpoint, json=payload, timeout=60)
            
            if response.status_code != 200:
                logger.error(f"ScrapeServ error: {response.status_code} - {response.text}")
                return {"error": f"HTTP {response.status_code}", "screenshots": []}
            
            # Parse multipart response
            content_type = response.headers.get("Content-Type", "")
            
            if "multipart/mixed" in content_type:
                return self._parse_multipart_response(response, url)
            else:
                # Try JSON response
                try:
                    return {"data": response.json(), "screenshots": []}
                except:
                    return {"error": "Unexpected response format", "screenshots": []}
                    
        except requests.exceptions.Timeout:
            logger.error(f"Timeout scraping URL: {url}")
            return {"error": "Timeout", "screenshots": []}
        except Exception as e:
            logger.error(f"Error scraping URL: {e}")
            return {"error": str(e), "screenshots": []}
    
    def _parse_multipart_response(self, response, original_url: str) -> dict:
        """Parse multipart/mixed response from ScrapeServ"""
        from email.message import Message
        from email.parser import BytesParser
        
        # Parse the multipart response
        msg = BytesParser().parsebytes(response.content)
        
        screenshots = []
        metadata = {}
        
        for part in msg.walk():
            content_type = part.get_content_type()
            content_disposition = part.get("Content-Disposition", "")
            
            if content_type == "application/json":
                # Parse metadata
                import json
                try:
                    metadata = json.loads(part.get_payload(decode=True))
                except:
                    pass
            
            elif "image" in content_type:
                # It's an image screenshot
                filename = part.get_filename(f"screenshot_{len(screenshots)}.jpg")
                
                # Save the screenshot
                image_data = part.get_payload(decode=True)
                screenshot_path = self._save_screenshot(original_url, image_data, filename)
                if screenshot_path:
                    screenshots.append(screenshot_path)
        
        return {"metadata": metadata, "screenshots": screenshots}
    
    def _save_screenshot(self, url: str, image_data: bytes, filename: str) -> Optional[str]:
        """Save screenshot to disk"""
        try:
            # Create a safe filename from the URL
            from urllib.parse import urlparse
            parsed = urlparse(url)
            safe_name = parsed.netloc + parsed.path.replace("/", "_")[:50]
            safe_name = "".join(c for c in safe_name if c.isalnum() or c in "_-")
            
            # Ensure unique filename
            import hashlib
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            safe_name = f"{safe_name}_{url_hash}.jpg"
            
            filepath = self.screenshots_dir / safe_name
            
            with open(filepath, "wb") as f:
                f.write(image_data)
            
            logger.info(f"Saved screenshot: {filepath}")
            return str(filepath)
            
        except Exception as e:
            logger.error(f"Error saving screenshot: {e}")
            return None
    
    def screenshot_post(self, post_url: str) -> dict:
        """
        Take a screenshot of a Reddit post
        
        Args:
            post_url: URL of the Reddit post
            
        Returns:
            Dictionary with screenshot paths
        """
        return self.scrape_url(post_url, wait=1500, max_screenshots=2)


def screenshot_posts():
    """Take screenshots of all posts that don't have screenshots"""
    import database
    
    posts = database.get_all_posts()
    
    client = ScrapeServClient()
    
    if not client.is_server_running():
        logger.warning("ScrapeServ is not running. Start it with: docker compose up")
        return 0
    
    screenshots_taken = 0
    
    for post in posts:
        if not post.screenshot_path:
            result = client.screenshot_post(post.permalink)
            if result.get("screenshots"):
                # Update database with screenshot path
                session = database.get_session()
                try:
                    post.screenshot_path = result["screenshots"][0]
                    session.commit()
                    screenshots_taken += 1
                except Exception as e:
                    session.rollback()
                    logger.error(f"Error updating screenshot path: {e}")
                finally:
                    session.close()
    
    logger.info(f"Screenshots taken: {screenshots_taken}")
    return screenshots_taken


if __name__ == "__main__":
    # Test if ScrapeServ is running
    client = ScrapeServClient()
    if client.is_server_running():
        print("✓ ScrapeServ is running!")
    else:
        print("✗ ScrapeServ is not running. Start it with: docker compose up")
