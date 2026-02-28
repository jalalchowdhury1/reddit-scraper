import scrape_top
import requests

def test_new_hierarchy():
    print("="*70)
    print("🎯 VERIFYING NEW HIERARCHY: JSON (Fail) -> HTML (Success)")
    print("="*70)

    sub = "dataisbeautiful"
    t_filter = "month"

    # Monkey patch to fail JSON but let HTML through
    original_get = requests.get

    def mocked_get(url, *args, **kwargs):
        if "json" in url:
            print(f"  [TEST] Simulating JSON Failure (429)...")
            resp = requests.Response()
            resp.status_code = 429
            return resp
        if "old.reddit.com" in url:
            print(f"  [TEST] Success! System correctly bypassed RSS to hit HTML Secondary.")
            return original_get(url, *args, **kwargs)
        return original_get(url, *args, **kwargs)

    requests.get = mocked_get

    try:
        posts = scrape_top.fetch_reddit_posts(sub, t_filter)
        
        if posts and len(posts) > 0:
            print(f"\n✅ SUCCESS: Captured {len(posts)} posts via HTML Fallback.")
            # Critical Check: Do we have real scores?
            first_score = posts[0].get('score', 0)
            if first_score > 0:
                print(f"✅ RANKING INTACT: Found real upvote score: {first_score}")
            else:
                print(f"❌ RANKING LOST: Score is 0. System might have skipped to RSS by mistake.")
        else:
            print("❌ TEST FAILED: No data recovered.")

    finally:
        requests.get = original_get

if __name__ == "__main__":
    test_new_hierarchy()
