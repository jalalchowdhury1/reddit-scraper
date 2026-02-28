import requests
import xml.etree.ElementTree as ET

# Test with a couple of different subreddits to ensure consistent RSS behavior
TEST_SUBS = ["todayilearned", "dataisbeautiful"]
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def test_rss_isolation():
    print("=" * 60)
    print("🛡️  ISOLATED RSS FAIL-SAFE DIAGNOSTIC TEST")
    print("=" * 60)
    
    for sub in TEST_SUBS:
        print(f"\n📡 Requesting RSS feed for r/{sub}...")
        url = f"https://www.reddit.com/r/{sub}/.rss"
        
        try:
            # 1. Test Network Connection & Rate Limits
            response = requests.get(url, headers=HEADERS, timeout=10)
            print(f"   ↳ HTTP Status Code: {response.status_code}")
            response.raise_for_status()
            
            # 2. Test XML Parsing
            root = ET.fromstring(response.content)
            posts = []
            ns = {'atom': 'http://www.w3.org/2005/Atom'}
            
            # 3. Test Data Extraction matches expected CSV format
            for entry in root.findall('atom:entry', ns):
                link_elem = entry.find('atom:link', ns)
                href = link_elem.attrib.get('href', '') if link_elem is not None else ''
                
                id_text = entry.findtext('atom:id', '', ns)
                post_id = id_text.split('_')[-1] if '_' in id_text else id_text
                
                posts.append({
                    'id': post_id,
                    'title': entry.findtext('atom:title', 'No Title', ns),
                    'selftext': "",  # RSS fallback
                    'permalink': href,
                    'score': 0       # RSS fallback
                })
            
            # 4. Validate Results
            if posts:
                print(f"   ✅ SUCCESS: Parsed {len(posts)} posts correctly.")
                print("   ↳ Data Structure Verification (First Post):")
                print(f"      - ID: {posts[0]['id']}")
                print(f"      - Title: {posts[0]['title'][:60]}...")
                print(f"      - Link: {posts[0]['permalink']}")
                print(f"      - Score Defaulted to: {posts[0]['score']}")
            else:
                print("   ❌ WARNING: Connected successfully, but found 0 posts. XML structure might have changed.")
                
        except requests.exceptions.HTTPError as e:
            print(f"   ❌ HTTP ERROR: Reddit rejected the RSS request: {e}")
        except ET.ParseError as e:
            print(f"   ❌ XML PARSE ERROR: Failed to read the RSS format: {e}")
        except Exception as e:
            print(f"   ❌ UNEXPECTED ERROR: {e}")

    print("\n" + "=" * 60)
    print("Diagnostic Complete.")

if __name__ == "__main__":
    test_rss_isolation()
