#!/bin/bash
# AM Reads from the Mac mini (4 Nov 2026, Jalal's yes). Cloudflare walls ritholtz.com
# for GitHub's runners (403 "Just a moment" on every page and /wp-json); the Mac's home
# connection gets the normal page. daily-reader-kick.sh runs this at 07:00, 08:30 and
# 10:00 BEFORE it starts am_reads.yml, so the GitHub run (now the backup) finds the
# list already current. Own clone + venv in ~/.local/share/am-reads, never the
# PyCharm copy. Install: cp mac/am-reads-mac.sh ~/.local/bin/am-reads-mac.sh
# Last line: "AM READS MAC PUSHED <sha>", "AM READS MAC NO CHANGE" or
# "AM READS MAC FAILED: <why>" (exit 1). AM_READS_* variables are for tests only.
export PATH=/opt/homebrew/bin:/usr/bin:/bin
BASE="${AM_READS_BASE:-$HOME/.local/share/am-reads}"
REMOTE="${AM_READS_REMOTE:-https://github.com/jalalchowdhury1/reddit-scraper.git}"
C="$BASE/reddit-scraper"
V="$BASE/venv"
say() { echo "$(date '+%F %T') AM READS MAC $*"; }
fail() { say "FAILED: $*"; exit 1; }

mkdir -p "$BASE"
[ -d "$C/.git" ] || timeout 300 git clone -q "$REMOTE" "$C" || fail "git clone"
cd "$C" || fail "no clone at $C"
rm -f .git/index.lock
git rebase --abort >/dev/null 2>&1
{ timeout 120 git fetch -q origin main && git reset -q --hard origin/main; } || fail "git sync"

# A brew Python upgrade can leave the venv broken: rebuild it once.
"$V/bin/python" -c "import requests, bs4, lxml, pandas" 2>/dev/null ||
  { /opt/homebrew/bin/python3 -m venv "$V" && "$V/bin/pip" install -q requests beautifulsoup4 lxml pandas; } ||
  fail "venv install"

timeout 120 "$V/bin/python" core/scrape_ritholtz.py || fail "scraper exit $? (its own FAILED line is above)"

git add -f data/ritholtz/
git diff --cached --quiet && { say "NO CHANGE"; exit 0; }
git -c user.name="am-reads-mac" -c user.email="am-reads-mac@users.noreply.github.com" \
  commit -q -m "Morning AM Reads update (Mac)" || fail "git commit"
for i in 1 2 3; do
  timeout 120 git pull -q --rebase -X theirs origin main && timeout 120 git push -q origin HEAD:main &&
    { say "PUSHED $(git rev-parse --short HEAD)"; exit 0; }
  git rebase --abort >/dev/null 2>&1
  sleep 10
done
fail "push after 3 tries"
