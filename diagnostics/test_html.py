import requests
from bs4 import BeautifulSoup

TEST_SUBS = ["todayilearned", "dataisbeautiful"]
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def test_html_isolation():
    print("=" * 60)
    print("🛡️  ISOLATED HTML FAIL-SAFE (old.reddit) DIAGNOSTIC TEST")
    print("=" * 60)
    
    for sub in TEST_SUBS:
        print(f"\n📡 Requesting HTML for r/{sub} (top/month)...")
        url = f"https://old.reddit.com/r/{sub}/top/?sort=top&t=month"
        
        try:
            # 1. Test Network Connection
            response = requests.get(url, headers=HEADERS, timeout=15)
            print(f"   ↳ HTTP Status Code: {response.status_code}")
            response.raise_for_status()
            
            # 2. Test HTML Parsing
            soup = BeautifulSoup(response.text, 'html.parser')
            posts = []
            
            # 3. Test Data Extraction
            for thing in soup.find_all('div', class_='thing')[:3]: # Grab top 3 for testing
                title_elem = thing.find('a', class_='title')
                if not title_elem: continue
                    
                score = 0
                score_elem = thing.find('div', class_='score unvoted')
                if score_elem and score_elem.get('title'):
                    try: score = int(score_elem.get('title'))
                    except ValueError: pass
                
                posts.append({
                    'id': thing.get('data-fullname', '').split('_')[-1],
                    'title': title_elem.text.strip(),
                    'permalink': thing.get('data-permalink', ''),
                    'score': score
                })
            
            # 4. Validate Results
            if posts:
                print(f"   ✅ SUCCESS: Parsed HTML structure correctly.")
                print("   ↳ Data Structure Verification (First Post):")
                print(f"      - ID: {posts[0]['id']}")
                print(f"      - Title: {posts[0]['title'][:60]}...")
                print(f"      - Link: {posts[0]['permalink']}")
                print(f"      - Score: {posts[0]['score']}  <-- (Notice we get actual scores back here!)")
            else:
                print("   ❌ WARNING: Connected, but found 0 posts. Reddit's HTML classes might have changed.")
                
        except requests.exceptions.HTTPError as e:
            print(f"   ❌ HTTP ERROR: Reddit rejected the request: {e}")
        except Exception as e:
            print(f"   ❌ UNEXPECTED ERROR: {e}")

    print("\n" + "=" * 60)
    print("Diagnostic Complete.")

if __name__ == "__main__":
    test_html_isolation()
