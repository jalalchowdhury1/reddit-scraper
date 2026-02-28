import scrape_top
import requests
import pandas as pd
from pathlib import Path
import os

def run_triple_threat_diagnostic():
    print("="*70)
    print("🛡️  ULTIMATE REDUNDANCY STRESS TEST: JSON -> RSS -> HTML")
    print("="*70)

    # Configuration for the test
    sub = "todayilearned"
    t_filter = "month"
    call_count = 0

    # 1. We "Monkey Patch" requests.get to control the failure sequence
    original_get = requests.get

    def mocked_get(url, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        
        # ATTEMPT 1: Simulate JSON Failure (Rate Limit)
        if "json" in url:
            print(f"  [TEST] Simulating JSON Failure (429 Rate Limit) for: {url}")
            mock_resp = requests.Response()
            mock_resp.status_code = 429
            return mock_resp
        
        # ATTEMPT 2: Simulate RSS Failure (Connection Error)
        if ".rss" in url:
            print(f"  [TEST] Simulating RSS Failure (Connection Timeout) for: {url}")
            raise requests.exceptions.ConnectionError("Simulated RSS Timeout")

        # ATTEMPT 3: Allow HTML to succeed
        if "old.reddit.com" in url:
            print(f"  [TEST] Allowing HTML Success for: {url}")
            return original_get(url, *args, **kwargs)
            
        return original_get(url, *args, **kwargs)

    # Apply the patch
    requests.get = mocked_get

    try:
        print(f"🎬 Starting official scrape for r/{sub}...")
        posts = scrape_top.fetch_reddit_posts(sub, t_filter)
        
        print("\n" + "-"*40)
        if posts and len(posts) > 0:
            # Check if we got data from the HTML method (the only one allowed to succeed)
            print(f"✅ TEST SUCCESS: Retrieved {len(posts)} posts via Tertiary Fallback.")
            
            # Verify structure
            sample = posts[0]
            required_keys = ['id', 'title', 'permalink', 'score']
            if all(k in sample for k in required_keys):
                print(f"✅ DATA VALID: All required columns ({required_keys}) are present.")
            
            # Verify URL formatting
            if sample['permalink'].startswith('https://www.reddit.com'):
                print(f"✅ URL VALID: Permalink is absolute: {sample['permalink'][:50]}...")
            else:
                print(f"❌ URL INVALID: Link is still relative!")

            # Verify File System
            scrape_top.save_posts_to_csv(posts, sub, t_filter)
            expected_path = Path(f"data/r_{sub}/posts.csv")
            if expected_path.exists():
                print(f"✅ DISK VALID: CSV successfully written to {expected_path}")
        else:
            print("❌ TEST FAILED: The fallback chain broke and returned no data.")

    except Exception as e:
        print(f"❌ STRUCTURAL ERROR: The test script itself crashed: {e}")
    finally:
        # Restore the original requests.get
        requests.get = original_get

    print("="*70)
    print("Diagnostic Complete.")

if __name__ == "__main__":
    run_triple_threat_diagnostic()
