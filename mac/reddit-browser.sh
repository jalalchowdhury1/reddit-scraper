#!/bin/bash
# Reddit top lists through a real browser on the Mac mini, then commit + push.
# launchd com.jalal.reddit-browser (mac/com.jalal.reddit-browser.plist) runs this
# at 07:35 and 19:35. It works in its OWN clone, never the working copy in
# ~/PycharmProjects, so it can't trip over half-done edits there.
# The work sits inside main() so bash has read all of it before `git reset
# --hard` below can replace this file mid-run.
#
# Log: ~/Library/Logs/reddit-browser.log. Each run starts with
# "== YYYY-MM-DD HH:MM:SS start" and ends well with "REDDIT PUSHED: N files"
# (or "NO REDDIT CHANGES (scraper exit 0)"). fleet-health checks exactly that.
#
# The REDDIT_BROWSER_* variables exist for tests/test_robustness.py only.

BASE="${REDDIT_BROWSER_BASE:-$HOME/.local/share/reddit-browser}"
LOG="${REDDIT_BROWSER_LOG:-$HOME/Library/Logs/reddit-browser.log}"
LOCK="$BASE/run.lock"

main() {
  set -u
  export PATH="/opt/homebrew/bin:/usr/bin:/bin"
  local clone="$BASE/reddit-scraper"
  local remote="${REDDIT_BROWSER_REMOTE:-https://github.com/jalalchowdhury1/reddit-scraper.git}"
  local py="${REDDIT_BROWSER_PY:-/opt/homebrew/bin/python3}"
  echo "== $(date '+%Y-%m-%d %H:%M:%S') start"

  # One run at a time: a manual run can overlap the scheduled one. A lock older
  # than 40 min belongs to a run that was killed (the scraper stops at 15-20 min).
  mkdir -p "$BASE"
  if ! mkdir "$LOCK" 2>/dev/null; then
    if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +40 2>/dev/null)" ]; then
      echo "old lock from a killed run: taking it over"
      rmdir "$LOCK" 2>/dev/null
      mkdir "$LOCK" 2>/dev/null || { echo "LOCK FAILED"; return 1; }
    else
      echo "ANOTHER RUN IS ACTIVE: skipping this one"
      return 0
    fi
  fi
  trap 'rmdir "$LOCK" 2>/dev/null' EXIT   # $LOCK is global: a local is gone by EXIT

  # Get the clone to exactly origin/main. A run killed mid-git (power cut, kill -9)
  # can leave an index.lock or a half-done rebase; anything worse (a broken clone)
  # gets one fresh clone. We hold run.lock, so no other git is running here.
  local try
  for try in 1 2; do
    if [ ! -d "$clone/.git" ]; then
      rm -rf "$clone"
      timeout 300 git clone -q "$remote" "$clone" || { echo "CLONE FAILED"; rm -rf "$clone"; return 1; }
    fi
    cd "$clone" || return 1
    rm -f .git/index.lock
    git rebase --abort >/dev/null 2>&1
    rm -rf .git/rebase-merge .git/rebase-apply
    if timeout 300 git fetch -q origin main && git reset -q --hard origin/main; then
      break
    fi
    [ "$try" = 2 ] && { echo "GIT SYNC FAILED"; return 1; }
    echo "clone looks broken: cloning it again"
    cd "$BASE" && rm -rf "$clone"
  done

  # -u: unbuffered, so a run killed by `timeout` still leaves its lines in the log.
  timeout 1200 "$py" -u core/scrape_reddit_browser.py --profile "$BASE/profile"
  local rc=$?

  git add -f data/r_*/posts.csv 2>/dev/null
  [ -f data/reddit_browser.json ] && git add -f data/reddit_browser.json
  if git diff --cached --quiet; then
    echo "NO REDDIT CHANGES (scraper exit $rc)"
    return "$rc"
  fi
  local n
  n=$(git diff --cached --name-only | wc -l | tr -d ' ')
  git commit -qm "Reddit via Mac browser: $n files" || { echo "COMMIT FAILED"; return 1; }
  # GitHub's daily scrape and am_reads.yml push here too: rebase and retry.
  local ok=0 i
  for i in 1 2 3; do
    timeout 120 git push -q origin HEAD:main && { ok=1; break; }
    timeout 300 git pull -q --rebase -X theirs origin main || git rebase --abort
    sleep "${REDDIT_BROWSER_RETRY_SLEEP:-5}"
  done
  [ "$ok" = 1 ] || { echo "PUSH FAILED after 3 tries"; return 1; }
  echo "REDDIT PUSHED: $n files in $(git rev-parse --short HEAD) (scraper exit $rc)"
  echo "== $(date '+%Y-%m-%d %H:%M:%S') done"
}

# Keep the log small: past ~500 KB keep the last 3000 lines. Truncate IN PLACE
# (same file), because launchd holds it open for appending.
mkdir -p "$(dirname "$LOG")"
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 500000 ]; then
  KEEP="$(tail -n 3000 "$LOG")"
  printf '%s\n' "$KEEP" > "$LOG"
fi

main "$@" >> "$LOG" 2>&1
