"""End-to-end checks of the real page in a headless browser (~80 s).

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
        await pg.wait_for_function("allData", timeout=20000)   # a cold local server can take ~2 s
        await pg.wait_for_timeout(1500)
        api = await pg.evaluate("allData")
        # Every tab shows exactly what the API sent (nothing read yet in a fresh browser).
        for key in ("monthly", "yearly", "news"):
            await pg.click(f'[data-tab="{key}"]:visible'); await pg.wait_for_timeout(400)
            cards = await pg.locator("#feed .item").count()
            label = await pg.inner_text("#progress-label")
            check(f"{key} shows all {len(api[key])} API posts", cards == len(api[key]), f"{cards} cards | {label}")
            total = api.get("totals", {}).get(key, 0)
            if key == "news":
                check("News label says last 7 days", "last 7 days" in label, label)
            elif total > cards:
                check(f"{key} label says top {cards} of {total}", f"top {cards} of {total}" in label, label)
        await pg.click('[data-tab="monthly"]:visible'); await pg.wait_for_timeout(500)

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
        await pg.click('[data-tab="monthly"]:visible'); await pg.wait_for_timeout(900)
        check("Tapping the active tab scrolls to top", await pg.evaluate("window.scrollY") < 5)

        # Phone tab bar: all 6 tabs at the bottom, on screen, not covered; header chips hidden.
        bar = await pg.evaluate("""[...document.querySelectorAll('#tabbar [data-tab]')].map(b => { const r = b.getBoundingClientRect();
            const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            return [b.dataset.tab, Math.round(r.left), Math.round(r.right), Math.round(r.bottom), !!hit && b.contains(hit)]; })""")
        chips_hidden = await pg.evaluate("getComputedStyle(document.getElementById('tabs')).display === 'none'")
        check("Phone: all 6 tabs in the bottom bar, on screen and tappable",
              len(bar) == 6 and chips_hidden and all(l >= 0 and r <= 390 and b <= 844 and ok for _, l, r, b, ok in bar), str(bar))
        # Header tucks away scrolling down, comes back scrolling up and on a tab switch.
        tucked = lambda: pg.evaluate("document.querySelector('header').classList.contains('tucked')")
        await pg.wait_for_timeout(500)
        for y in (300, 600, 900):
            await pg.evaluate(f"window.scrollTo(0, {y})"); await pg.wait_for_timeout(120)
        await pg.wait_for_timeout(300)
        down = await tucked()
        await pg.evaluate("window.scrollTo(0, 700)"); await pg.wait_for_timeout(400)
        up = await tucked()
        await pg.evaluate("window.scrollTo(0, 1200)"); await pg.wait_for_timeout(400)
        await pg.click('[data-tab="yearly"]:visible'); await pg.wait_for_timeout(500)
        on_switch = await tucked()
        check("Header tucks scrolling down, returns scrolling up and on a tab switch", down and not up and not on_switch, f"{down}/{up}/{on_switch}")
        await pg.click('[data-tab="monthly"]:visible'); await pg.wait_for_timeout(300)
        await pg.evaluate("window.scrollTo(0, 0)"); await pg.wait_for_timeout(500)

        # Pull to refresh: a real touch drag down from the top re-fetches; a short one doesn't.
        cdp = await ctx.new_cdp_session(pg)
        fetches = []
        pg.on("request", lambda r: "/api/data" in r.url and fetches.append(r.url))
        async def drag(y1, y2):
            await cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": 200, "y": y1}]})
            for y in range(y1, y2 + 1, 12):
                await cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": 200, "y": y}]})
            await cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        await pg.evaluate("hideToast()")
        await drag(300, 340); await pg.wait_for_timeout(1200)
        short_ok = not fetches and not (await pg.inner_text("#toast-msg")).startswith("Refreshed")
        await drag(300, 520)
        # the local dev server answers one request at a time, so this can take a while
        try: await pg.wait_for_function("document.getElementById('toast-msg').textContent.startsWith('Refreshed')", timeout=30000)
        except Exception: pass
        msg = await pg.evaluate("document.getElementById('toast-msg').textContent")
        check("Pull down at the top refreshes; a short pull doesn't", short_ok and len(fetches) == 1 and msg.startswith("Refreshed"),
              f"short ok={short_ok} | {len(fetches)} fetch | {msg} | " + str(await pg.evaluate("[document.getElementById('ptr').className, document.getElementById('toast-msg').textContent, window.scrollY, loadError]")))
        check("Refresh leaves you at the top", await pg.evaluate("window.scrollY") < 5)
        n_errs = len(errs)
        await ctx.set_offline(True)
        await pg.evaluate("hideToast()"); await drag(300, 520)
        try: await pg.wait_for_function("document.getElementById('toast-msg').textContent.includes('offline')", timeout=25000)
        except Exception: pass
        off_msg = await pg.evaluate("document.getElementById('toast-msg').textContent")
        await ctx.set_offline(False)
        # Offline on purpose: its failed-request console lines are expected. Page crashes still count.
        errs[n_errs:] = [e for e in errs[n_errs:] if not e.startswith("console:")]
        check("Offline pull says so (the worker's saved copy), never 'Refreshed'", off_msg.startswith("You're offline"), off_msg)

        # News: relative times + one copy per story
        await pg.click('[data-tab="news"]:visible'); await pg.wait_for_timeout(500)
        nfeed = await pg.inner_text("#feed")
        check("News shows relative time", ("ago" in nfeed) or ("yesterday" in nfeed))
        titles = await pg.locator("#feed .item-title").all_inner_texts()
        norm = ["".join(c for c in t.lower() if c.isalnum())[:70] for t in titles]
        check("News has one copy per headline", len(norm) == len(set(norm)), f"{len(norm)} cards")

        # AM Reads: SatPost after its own label, if any
        await pg.click('[data-tab="ritholtz"]:visible'); await pg.wait_for_timeout(500)
        am = await pg.inner_text("#feed")
        check("AM Reads renders", ("AM Reads" in am) or ("Weekend Reads" in am) or ("aren't out yet" in am), am.split("\n")[0][:50])
        # GitHub Trending: GitHub's own top 10, in its order, with its star counts.
        await pg.click('[data-tab="github"]:visible'); await pg.wait_for_timeout(500)
        gh = api.get("github", [])
        gcards = await pg.locator("#feed .item").count()
        glabel = await pg.inner_text("#progress-label")
        check("GitHub tab shows the API's top 10", gcards == len(gh) == 10, f"{gcards} cards / {len(gh)} in API | {glabel}")
        if api.get("totals", {}).get("github", 0) > 10:
            check("GitHub label says top 10 of N", f"top 10 of {api['totals']['github']}" in glabel, glabel)
        gtitles = await pg.locator("#feed .item-title").all_inner_texts()
        check("GitHub cards in GitHub's order", gtitles == [i["title"] for i in gh], f"{gtitles[:2]}")
        gmeta = await pg.locator("#feed .item .meta").first.inner_text()
        check("GitHub card shows #1 + GitHub's own star counts",
              gmeta.startswith("#1") and f"+{gh[0]['stars_today']} stars today" in gmeta and f"{gh[0]['stars']} stars" in gmeta, gmeta)
        check("GitHub tab has its label", "Trending today on GitHub" in await pg.inner_text("#feed"))
        await pg.locator("#feed .item").first.locator('[data-act="read"]').click(); await pg.wait_for_timeout(700)
        check("Marking a GitHub repo read hides it", await pg.locator("#feed .item").count() == gcards - 1, await pg.inner_text("#progress-label"))
        streak1 = await pg.inner_text("#streak")
        check("Today line counts it: '1 cleared today'", streak1.startswith("1 cleared today"), streak1)
        await pg.click("#toast-undo"); await pg.wait_for_timeout(700)
        check("Undo brings the repo back", await pg.locator("#feed .item").count() == gcards)
        check("Undo takes it off the today line", "cleared" not in await pg.inner_text("#streak"), await pg.inner_text("#streak"))
        s = await pg.evaluate("""(() => { const saved = cloudReadAt, at = (n) => new Date(Date.now() - n * 864e5).toISOString();
            cloudReadAt = { x1: at(1), x2: at(2), x3: at(2), bad: 'not a date' }; countReadDays(); render();
            const a = document.getElementById('streak').textContent;
            cloudReadAt = { ...cloudReadAt, x4: at(0) }; countReadDays(); render();
            const b = document.getElementById('streak').textContent;
            cloudReadAt = saved; countReadDays(); render(); return [a, b]; })()""")
        check("Streak: nothing today asks to keep it; one today extends it",
              s[0] == "Clear one to keep your 2-day streak" and s[1].startswith("1 cleared today") and "3-day streak" in s[1], str(s))
        print("   footer:", await pg.inner_text("#updated"))
        footer = await pg.inner_text("#updated")
        check("Footer shows update times", "Updated:" in footer)
        if api["updated"].get("reddit"):
            check("Footer shows when Reddit last came from the Mac", "Reddit " in footer, footer)
        if api["updated"].get("github"):
            check("Footer shows when GitHub Trending last landed", "GitHub " in footer, footer)
        # Order switch (Monthly/Yearly): Most upvotes = the same posts high to low, remembered; Mixed = the server's order.
        live_nums = "visibleItems.filter(i => !i._kept).map(upvoteNum)"
        await pg.click('[data-tab="monthly"]:visible'); await pg.wait_for_timeout(400)
        mix_ids = await pg.evaluate("visibleItems.map(i => String(i.id)).sort().join()")
        await pg.click('[data-act="sort"][data-sort="top"]'); await pg.wait_for_timeout(400)
        nums = await pg.evaluate(live_nums)
        same = await pg.evaluate("visibleItems.map(i => String(i.id)).sort().join()") == mix_ids
        check("Most upvotes: Monthly high to low, same posts", nums == sorted(nums, reverse=True) and min(nums) > 0 and same, str(nums[:6]))
        await pg.click('[data-tab="yearly"]:visible'); await pg.wait_for_timeout(400)
        ynums = await pg.evaluate(live_nums)
        check("Most upvotes applies to Yearly too", ynums == sorted(ynums, reverse=True), str(ynums[:6]))
        await pg.reload(wait_until="load")
        await pg.wait_for_function("allData && (readLoaded || syncBroken)", timeout=20000); await pg.wait_for_timeout(500)
        remembered = await pg.evaluate("sortTop && document.querySelector('[data-sort=\"top\"]').classList.contains('on')")
        check("The order choice is remembered", remembered)
        await pg.click('[data-act="sort"][data-sort="mix"]'); await pg.wait_for_timeout(400)
        back = await pg.evaluate("""visibleItems.filter(i => !i._kept).map(i => String(i.id)).join() ===
            allData[currentTab].filter(i => !isRead(i)).map(i => String(i.id)).join()""")
        check("Mixed = the server's order again", back)
        # Sub chips: one tap = one subreddit; the label says so; Mark all read stays inside it; tap again = All.
        await pg.click('[data-tab="monthly"]:visible'); await pg.wait_for_timeout(400)
        all_cards = await pg.locator("#feed .item").count()
        chip = pg.locator('#feed .sub-chips [data-act="sub"]').nth(1)
        sub, chip_n = await chip.get_attribute("data-sub"), int(await chip.locator(".count").inner_text())
        await chip.click(); await pg.wait_for_timeout(400)
        subs_shown = await pg.evaluate("[...new Set(visibleItems.map(subKey))]")
        label = await pg.inner_text("#progress-label")
        check("Sub chip shows only that sub, count matches the chip",
              subs_shown == [sub] and await pg.locator("#feed .item").count() == chip_n and " only" in label, f"{sub}: {subs_shown} | {label}")
        others = "itemsFor('monthly').filter(i => subKey(i) !== subFilter.monthly && !isRead(i)).length"
        before_others = await pg.evaluate(others)
        await pg.click("#btn-markall"); await pg.wait_for_timeout(700)
        caught = await pg.inner_text("#feed")
        check("Mark all read stays inside the sub, chips stay to get back",
              await pg.evaluate(others) == before_others and "All caught up" in caught
              and await pg.locator("#feed .sub-chips").count() == 1, caught[:80])
        await pg.click("#toast-undo"); await pg.wait_for_timeout(700)
        await pg.click(f'#feed .sub-chips [data-sub="{sub}"]'); await pg.wait_for_timeout(400)
        check("Tapping the chosen chip again shows All",
              await pg.evaluate("subFilter.monthly === null") and await pg.locator("#feed .item").count() == all_cards,
              f"{await pg.locator('#feed .item').count()} vs {all_cards}")
        # Cleared-today list: tap "N cleared today" -> today's read items, newest first; untick = back to unread.
        first_id = await pg.locator("#feed .item").first.get_attribute("data-id")
        await pg.locator("#feed .item").first.locator('[data-act="read"]').click(); await pg.wait_for_timeout(700)
        n_today = await pg.evaluate("readByDay[etDate()] || 0")
        await pg.click("#btn-cleared"); await pg.wait_for_timeout(400)
        head = await pg.inner_text("#feed .cleared-label")
        top_id = await pg.locator("#feed .item").first.get_attribute("data-id")
        check("Cleared list opens with the item just cleared on top",
              f"Cleared today · {n_today}" in head and top_id == first_id, f"{head} | {top_id} vs {first_id}")
        await pg.locator("#feed .item").first.locator('[data-act="read"]').click(); await pg.wait_for_timeout(700)
        gone = await pg.locator(f'#feed .item[data-id="{first_id}"]').count() == 0
        check("Unticking in the list marks it unread and drops it", gone and not await pg.evaluate(f"cloudReadPosts.has('{first_id}')"))
        await pg.click('[data-tab="monthly"]:visible'); await pg.wait_for_timeout(400)
        check("Tapping the tab closes the list",
              not await pg.evaluate("viewCleared") and await pg.locator("#feed .item").count() == all_cards)
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
        await pg.click('[data-tab="news"]:visible'); await pg.wait_for_timeout(400)
        n = await pg.locator("#feed .notice").count()
        check("Stale News shows a notice", n == 1, (await pg.locator("#feed .notice").inner_text())[:90] if n else "")
        await pg.click('[data-tab="monthly"]:visible'); await pg.wait_for_timeout(400)
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
            await pg2.click(f'[data-tab="{key}"]:visible'); await pg2.wait_for_timeout(400)
            n = await pg2.locator("#feed .notice").count()
            check(f"Stale Reddit shows a notice on {key}", n == 1 and "Mac mini" in await pg2.inner_text("#feed .notice"))
        await pg2.click('[data-tab="news"]:visible'); await pg2.wait_for_timeout(400)
        check("News shows no Reddit notice", "Mac mini" not in await pg2.inner_text("#feed"))
        await pg2.close()

        # ---------- stale GitHub notice (the 6-hourly job stopped) ----------
        pg3 = await ctx.new_page()
        async def stale_github(route):
            r = await route.fetch(); d = await r.json()
            d["updated"]["github"] = "2026-09-01T12:41:00Z"
            d["updated"]["reddit"] = datetime.now(timezone.utc).isoformat()
            await route.fulfill(response=r, body=json.dumps(d), headers={**r.headers, "content-type": "application/json"})
        await pg3.route("**/api/data", stale_github)
        await pg3.goto(BASE + "/", wait_until="load"); await pg3.wait_for_timeout(2500)
        await pg3.keyboard.press("5"); await pg3.wait_for_timeout(400)   # key 5 = the GitHub tab
        check("Key 5 opens the GitHub tab", await pg3.evaluate("currentTab") == "github")
        n = await pg3.locator("#feed .notice").count()
        check("Stale GitHub shows a notice", n == 1 and "GitHub Trending" in await pg3.inner_text("#feed .notice"))
        await pg3.keyboard.press("6"); await pg3.wait_for_timeout(400)
        check("Key 6 opens Favorites", await pg3.evaluate("currentTab") == "favorites")
        await pg3.click('[data-tab="monthly"]:visible'); await pg3.wait_for_timeout(400)
        check("Monthly shows no GitHub notice", "GitHub Trending" not in await pg3.inner_text("#feed"))
        await pg3.close()

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

        check("Desktop: header chips, no bottom tab bar", await pg.evaluate(
            "getComputedStyle(document.getElementById('tabbar')).display === 'none' && getComputedStyle(document.getElementById('tabs')).display !== 'none'"))
        cols = await pg.evaluate("getComputedStyle(document.getElementById('feed')).gridTemplateColumns.split(' ').length")
        check("Desktop keeps 2 columns", cols == 2, str(cols))
        check("No JS errors (desktop)", not errs2, "; ".join(errs2)[:200])
        await ctx.close()

        # ---------- kept: an unread post that drops out of the top 50 stays ----------
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
        pg = await ctx.new_page()
        errs3 = []
        pg.on("pageerror", lambda e: errs3.append(str(e)))
        await pg.goto(BASE + "/", wait_until="load")  # 1st visit remembers the lists
        await pg.wait_for_function("allData", timeout=20000); await pg.wait_for_timeout(1000)
        first = await pg.evaluate("({gone: allData.monthly.slice(0, 2).map(i => String(i.id)),"
                                  " subs: allData.monthly.slice(0, 2).map(i => i.source.slice(2)),"
                                  " mover: String(allData.yearly[0].id)})")
        gone, mover = first["gone"], first["mover"]
        mode = {"drop": True, "move": False, "drop_sub": None}
        async def reshuffle(route):
            r = await route.fetch(); d = await r.json()
            if mode["drop"]:
                d["monthly"] = [i for i in d["monthly"] if str(i["id"]) not in gone]
            if mode["move"]:   # the server moved a Yearly post into Monthly ("one of each")
                post = next(i for i in d["yearly"] if str(i["id"]) == mover)
                d["yearly"] = [i for i in d["yearly"] if str(i["id"]) != mover]
                d["monthly"].append(post)
            if mode["drop_sub"]:
                d["reddit_subs"] = [s for s in d["reddit_subs"] if s.lower() != mode["drop_sub"].lower()]
            await route.fulfill(response=r, body=json.dumps(d), headers={**r.headers, "content-type": "application/json"})
        await pg.route("**/api/data", reshuffle)
        async def load_monthly():
            await pg.reload(wait_until="load")
            await pg.wait_for_function("allData && (readLoaded || syncBroken)", timeout=20000)
            await pg.click('[data-tab="monthly"]:visible'); await pg.wait_for_timeout(400)
        kept_ids = lambda: pg.evaluate("[...document.querySelectorAll('#feed .kept-label ~ .item')].map(e => e.dataset.id)")
        label = lambda: pg.inner_text("#progress-label")
        await load_monthly()
        live_n = await pg.evaluate("allData.monthly.length")
        check("Unread posts that drop out stay, under their own label", sorted(await kept_ids()) == sorted(gone), f"{await kept_ids()} vs {gone}")
        check("Label counts the kept posts", f"top {live_n} of" in await label() and "+ 2 kept" in await label(), await label())
        check("Tab badge counts the kept posts", await pg.inner_text('[data-tab="monthly"]:visible .count') == str(live_n + 2))
        read_id = (await kept_ids())[0]
        await pg.click('#feed .kept-label ~ .item [data-act="read"]'); await pg.wait_for_timeout(600)
        check("Reading a kept post removes it", await kept_ids() == [x for x in gone if x != read_id] and "+ 1 kept" in await label(), await label())
        await pg.evaluate("setShowRead(true)"); await pg.wait_for_timeout(300)
        check("Eye button shows a read kept post", read_id in await kept_ids(), str(await kept_ids()))
        await pg.evaluate("setShowRead(false)"); await pg.wait_for_timeout(300)
        # Reviewer bug: a data reload right after marking read (resume after 20 min) must not lose it.
        await pg.evaluate("readLoaded = true; loadData()"); await pg.wait_for_timeout(1500)
        await pg.evaluate(f"setRead([{json.dumps(read_id)}], false)"); await pg.wait_for_timeout(600)
        check("Undo after a data reload brings a kept post back", read_id in await kept_ids(), str(await kept_ids()))
        await pg.click('[data-act="keptread"]'); await pg.wait_for_timeout(600)
        check("'Mark these read' clears the section", await pg.locator("#feed .kept-label").count() == 0
              and "kept" not in await label(), await label())
        # Expiry counts from when a post LEFT the list: unread again, one left long ago.
        await pg.evaluate(f"setRead({json.dumps(gone)}, false)"); await pg.wait_for_timeout(800)
        await pg.evaluate(f"""(() => {{ const m = JSON.parse(localStorage.getItem('dr_kept'));
            m.monthly[{json.dumps(gone[0])}].gone = '2020-01-01'; localStorage.setItem('dr_kept', JSON.stringify(m)); }})()""")
        await load_monthly()
        check("A kept post expires 30 days after it left", await kept_ids() == [gone[1]], str(await kept_ids()))
        # A Yearly post the server moves into Monthly shows once, not kept in Yearly too.
        mode["move"] = True
        await load_monthly()
        seen_ids = await pg.evaluate("[...document.querySelectorAll('#feed .item')].map(e => e.dataset.id)")
        await pg.click('[data-tab="yearly"]:visible'); await pg.wait_for_timeout(400)
        seen_ids += await pg.evaluate("[...document.querySelectorAll('#feed .item')].map(e => e.dataset.id)")
        check("A post moved between tabs shows once", seen_ids.count(mover) == 1, f"{seen_ids.count(mover)}x")
        # Back in the live list = shown once, in its normal place.
        mode.update(drop=False, move=False)
        await load_monthly()
        cards = await pg.evaluate("[...document.querySelectorAll('#feed .item')].map(e => e.dataset.id)")
        check("A post back in the top 50 shows once, no kept section",
              await pg.locator("#feed .kept-label").count() == 0 and len(cards) == len(set(cards)) and gone[1] in cards, f"{len(cards)} cards")
        # A sub the server stopped tracking: its kept posts go too.
        mode.update(drop=True, drop_sub=first["subs"][1])
        await load_monthly()
        want = [g for g, s in zip(gone, first["subs"]) if s.lower() != first["subs"][1].lower()]
        check("Kept posts from a removed sub disappear", sorted(await kept_ids()) == sorted(want), f"{await kept_ids()} vs {want}")
        await pg.evaluate(f"setRead({json.dumps(gone)}, false)")
        check("No JS errors (kept)", not errs3, "; ".join(errs3)[:200])
        await ctx.close()

        # ---------- quiet subs (9 Oct 2026) ----------
        # Seed a history: every post of the sub with the most Monthly slots sat
        # unread 6 days, every other sub's post was opened. That sub must get
        # quieted to level 2: a quarter of its slots, the tab refilled to its size.
        import math
        actx = await b.new_context()
        api = await (await actx.request.get(BASE + "/api/data")).json()
        await actx.close()
        subs = {}
        for i in api["monthly"]:
            subs.setdefault(i["source"].lower(), []).append(i)
        big = max(subs, key=lambda k: len(subs[k]))
        d6 = (datetime.now(timezone.utc).date() - __import__("datetime").timedelta(days=6)).isoformat()
        qlog = {i["id"]: {"s": i["source"][2:].lower(), "d": d6, **({} if i["source"].lower() == big else {"e": d6})}
                for tab in ("monthly", "yearly") for i in api[tab]}
        ctx = await b.new_context(viewport={"width": 390, "height": 844}, service_workers="block")
        await ctx.add_init_script(f"if(!sessionStorage.qs){{localStorage.setItem('dr_qlog', {json.dumps(json.dumps(qlog))});sessionStorage.qs=1}}")
        pg = await ctx.new_page()
        errs4 = []
        pg.on("pageerror", lambda e: errs4.append(str(e)))
        await pg.goto(BASE)
        await pg.wait_for_selector("#feed .item", timeout=20000)
        await pg.wait_for_selector(".quiet-label", timeout=20000)
        srcs = await pg.eval_on_selector_all("#feed > .item .src .name", "els => els.map(e => e.textContent.toLowerCase())")
        want = max(1, math.ceil(len(subs[big]) * 0.25))
        check(f"Quiet: {big} cut to its top quarter", sum(s.startswith(big) for s in srcs) == want, f"{sum(s.startswith(big) for s in srcs)} vs {want}")
        check("Quiet: tab refilled to the server's size", len(srcs) == len(api["monthly"]), f"{len(srcs)} vs {len(api['monthly'])}")
        label = await pg.inner_text("#progress-label")
        check("Quiet: progress row counts quieted posts", "quieted" in label, label)
        check("Quiet: the why line names the sub", "sat unread 3+ days" in await pg.inner_text(".quiet-why"))
        await pg.click("[data-act=quietshow]")
        check("Quiet: Show reveals them", await pg.locator("#feed > .item").count() == len(srcs) + len(subs[big]) - want)
        await pg.click("[data-act=unquiet]")
        await pg.wait_for_timeout(400)
        check("Quiet: Stop brings the sub back, no kept leftovers",
              await pg.locator(".quiet-label").count() == 0 and "kept" not in await pg.inner_text("#progress-label"),
              await pg.inner_text("#progress-label"))
        check("No JS errors (quiet)", not errs4, "; ".join(errs4)[:200])
        await ctx.close()
        await b.close()
    print(f"\n{sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)

asyncio.run(main())
