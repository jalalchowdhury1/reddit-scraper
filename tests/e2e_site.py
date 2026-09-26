"""End-to-end checks of the real page in a headless browser (~40 s).

usage: python3 tests/e2e_site.py [base_url]     (default http://localhost:8791)
  local: .venv/bin/uvicorn server:app --port 8791, then run this
  live:  python3 tests/e2e_site.py https://reddit-scraper-lyart.vercel.app

Needs Playwright (the Mac's /opt/homebrew/bin/python3 has it; the .venv does not).
Every run is a fresh throwaway headless browser: it never touches a real Chrome
profile, and marks read/unread only in that throwaway browser's storage.
Not collected by pytest (the name doesn't start with test_). Exit 1 = a check failed.
"""
import sys, asyncio, json
from datetime import datetime, timezone
from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8791"
results = []

def check(name, ok, detail=""):
    results.append(ok)
    print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(headless=True)

        # ---------- phone ----------
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, color_scheme="dark")
        pg = await ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: m.type == "error" and "favicons" not in m.text and errs.append("console: " + m.text))
        await pg.goto(BASE + "/", wait_until="load")
        await pg.wait_for_timeout(3000)
        api = await pg.evaluate("allData")
        # Every tab shows exactly what the API sent (nothing read yet in a fresh browser).
        for key in ("monthly", "yearly", "news"):
            await pg.click(f'[data-tab="{key}"]'); await pg.wait_for_timeout(400)
            cards = await pg.locator("#feed .item").count()
            label = await pg.inner_text("#progress-label")
            check(f"{key} shows all {len(api[key])} API posts", cards == len(api[key]), f"{cards} cards | {label}")
            total = api.get("totals", {}).get(key, 0)
            if key == "news":
                check("News label says last 7 days", "last 7 days" in label, label)
            elif total > cards:
                check(f"{key} label says top {cards} of {total}", f"top {cards} of {total}" in label, label)
        await pg.click('[data-tab="monthly"]'); await pg.wait_for_timeout(500)

        feed = await pg.inner_text("#feed")
        want = [i["upvotes"] for i in api["monthly"][:5]]
        metas = [await m.inner_text() for m in (await pg.locator("#feed .item .meta").all())[:5]]
        check("Monthly upvotes = the API's real numbers", all(w and f"{w} upvotes" in m for w, m in zip(want, metas)), f"{want[:3]} / {[m[:20] for m in metas[:2]]}")
        check("Monthly says top 50 of N", "top 50 of" in await pg.inner_text("#progress-label"), await pg.inner_text("#progress-label"))
        check("Monthly has no AskHistorians", "r/AskHistorians" not in feed)

        # open a title: stays unread, gains "Opened"
        before = await pg.inner_text("#progress-label")
        first = pg.locator("#feed .item").first
        fid = await first.get_attribute("data-id")
        title = await first.locator(".item-title").inner_text()
        async with ctx.expect_page() as pop:
            await first.locator(".item-title").click()
        popup = await pop.value
        await popup.close()
        await pg.wait_for_timeout(600)
        card = pg.locator(f'#feed .item[data-id="{fid}"]')
        after = await pg.inner_text("#progress-label")
        check("Opening leaves it unread", before == after, f"{before} -> {after}")
        meta = await card.locator(".meta").inner_text()
        check("Opened card shows 'Opened' tag", "Opened" in meta, meta)
        check("Opened card has hollow-dot class", "opened" in (await card.get_attribute("class")))

        # come back after 15 s -> prompt; tap it -> marked read
        await pg.evaluate("leftPage(); awayAt = Date.now() - 15000; backOnPage()")
        await pg.wait_for_timeout(300)
        msg = await pg.inner_text("#toast-msg"); btn = await pg.inner_text("#toast-undo")
        check("Return prompt asks 'Done with ...?'", msg.startswith("Done with") and btn == "Mark read", f"{msg} / {btn}")
        await pg.click("#toast-undo"); await pg.wait_for_timeout(700)
        after2 = await pg.inner_text("#progress-label")
        check("Prompt's Mark read marks it read", after2 != after, f"{after} -> {after2}")
        await pg.click("#toast-undo"); await pg.wait_for_timeout(700)  # Undo
        check("Undo restores it", await pg.inner_text("#progress-label") == after)

        # quick peek (<10 s) -> no prompt
        await pg.evaluate("pendingOpened = [document.querySelector('#feed .item').dataset.id]; document.getElementById('toast').classList.remove('show'); leftPage(); awayAt = Date.now() - 4000; backOnPage()")
        await pg.wait_for_timeout(300)
        shown = await pg.evaluate("document.getElementById('toast').classList.contains('show')")
        check("Quick peek gets no prompt", not shown)

        # tap-to-expand blurb (find a card with a desc)
        descs = pg.locator("#feed .desc")
        nd = await descs.count()
        if nd:
            d0 = descs.first
            await d0.click(); await pg.wait_for_timeout(200)
            check("Tapping a blurb expands it", "open" in (await d0.get_attribute("class")))
        else:
            check("Tapping a blurb expands it (no blurbs in current data)", True, "skipped: Monthly has no self-post text until the next scrape")

        # active tab tap -> top
        await pg.evaluate("window.scrollTo(0, 1500)"); await pg.wait_for_timeout(300)
        await pg.click('[data-tab="monthly"]'); await pg.wait_for_timeout(900)
        check("Tapping the active tab scrolls to top", await pg.evaluate("window.scrollY") < 5)

        # News: relative times + one copy per story
        await pg.click('[data-tab="news"]'); await pg.wait_for_timeout(500)
        nfeed = await pg.inner_text("#feed")
        check("News shows relative time", ("ago" in nfeed) or ("yesterday" in nfeed))
        titles = await pg.locator("#feed .item-title").all_inner_texts()
        norm = ["".join(c for c in t.lower() if c.isalnum())[:70] for t in titles]
        check("News has one copy per headline", len(norm) == len(set(norm)), f"{len(norm)} cards")

        # AM Reads: SatPost after its own label, if any
        await pg.click('[data-tab="ritholtz"]'); await pg.wait_for_timeout(500)
        am = await pg.inner_text("#feed")
        check("AM Reads renders", ("AM Reads" in am) or ("Weekend Reads" in am) or ("aren't out yet" in am), am.split("\n")[0][:50])
        print("   footer:", await pg.inner_text("#updated"))
        footer = await pg.inner_text("#updated")
        check("Footer shows update times", "Updated:" in footer)
        if api["updated"].get("reddit"):
            check("Footer shows when Reddit last came from the Mac", "Reddit " in footer, footer)
        ow = await pg.evaluate("document.documentElement.scrollWidth > window.innerWidth")
        check("No sideways scroll on phone", not ow)
        check("No JS errors (phone)", not errs, "; ".join(errs)[:200])
        await ctx.close()

        # ---------- stale News notice (API response edited) ----------
        # service_workers="block": route() can't see fetches the page's service worker makes.
        ctx = await b.new_context(viewport={"width": 1440, "height": 900}, color_scheme="light",
                                  service_workers="block")
        pg = await ctx.new_page()
        errs2 = []
        pg.on("pageerror", lambda e: errs2.append(str(e)))
        async def stale(route):
            r = await route.fetch(); d = await r.json()
            d["updated"]["news"] = "2026-09-20T08:00:00Z"
            d["updated"]["reddit"] = datetime.now(timezone.utc).isoformat()  # isolate: Reddit fresh
            await route.fulfill(response=r, body=json.dumps(d), headers={**r.headers, "content-type": "application/json"})
        await pg.route("**/api/data", stale)
        await pg.goto(BASE + "/", wait_until="load"); await pg.wait_for_timeout(2500)
        await pg.click('[data-tab="news"]'); await pg.wait_for_timeout(400)
        n = await pg.locator("#feed .notice").count()
        check("Stale News shows a notice", n == 1, (await pg.locator("#feed .notice").inner_text())[:90] if n else "")
        await pg.click('[data-tab="monthly"]'); await pg.wait_for_timeout(400)
        check("Other tabs show no News notice", await pg.locator("#feed .notice").count() == 0)

        # ---------- stale Reddit notice (Mac mini stopped refreshing) ----------
        pg2 = await ctx.new_page()
        async def stale_reddit(route):
            r = await route.fetch(); d = await r.json()
            d["updated"]["reddit"] = "2026-09-01T11:35:00Z"
            await route.fulfill(response=r, body=json.dumps(d), headers={**r.headers, "content-type": "application/json"})
        await pg2.route("**/api/data", stale_reddit)
        await pg2.goto(BASE + "/", wait_until="load"); await pg2.wait_for_timeout(2500)
        for key in ("monthly", "yearly"):
            await pg2.click(f'[data-tab="{key}"]'); await pg2.wait_for_timeout(400)
            n = await pg2.locator("#feed .notice").count()
            check(f"Stale Reddit shows a notice on {key}", n == 1 and "Mac mini" in await pg2.inner_text("#feed .notice"))
        await pg2.click('[data-tab="news"]'); await pg2.wait_for_timeout(400)
        check("News shows no Reddit notice", "Mac mini" not in await pg2.inner_text("#feed"))
        await pg2.close()

        # desktop keyboard: j, r, u
        await pg.keyboard.press("j"); await pg.wait_for_timeout(200)
        b1 = await pg.inner_text("#progress-label")
        await pg.keyboard.press("r"); await pg.wait_for_timeout(600)
        b2 = await pg.inner_text("#progress-label")
        await pg.keyboard.press("u"); await pg.wait_for_timeout(600)
        b3 = await pg.inner_text("#progress-label")
        check("Keys: r marks read, u undoes", b1 != b2 and b1 == b3, f"{b1} -> {b2} -> {b3}")
        # Reviewer bug: Enter after an ignored prompt must NOT mark anything read
        e1 = await pg.inner_text("#progress-label")
        await pg.evaluate("""pendingOpened = [document.querySelector('#feed .item').dataset.id];
            leftPage(); awayAt = Date.now() - 15000; backOnPage();
            document.getElementById('toast-undo').focus(); hideToast();""")
        await pg.keyboard.press("Enter"); await pg.wait_for_timeout(600)
        pages = ctx.pages
        for extra in pages[1:]: await extra.close()
        e2 = await pg.inner_text("#progress-label")
        check("Enter after an ignored prompt marks nothing", e1 == e2, f"{e1} -> {e2}")

        # Focus follows the item when a card above it leaves the list
        await pg.evaluate("focusIndex = 1; paintFocus(false)")
        fid = await pg.evaluate("focusId")
        first_id = await pg.evaluate("visibleItems[0].id")
        await pg.evaluate(f"setRead(['{first_id}'], true)"); await pg.wait_for_timeout(500)
        now_id = await pg.evaluate("document.querySelector('#feed .item.focused').dataset.id")
        check("Focus stays on the same card", now_id == fid, f"{fid} -> {now_id}")
        await pg.evaluate(f"setRead(['{first_id}'], false)"); await pg.wait_for_timeout(400)

        cols = await pg.evaluate("getComputedStyle(document.getElementById('feed')).gridTemplateColumns.split(' ').length")
        check("Desktop keeps 2 columns", cols == 2, str(cols))
        check("No JS errors (desktop)", not errs2, "; ".join(errs2)[:200])
        await b.close()
    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)

asyncio.run(main())
