#!/bin/bash
# Reddit top lists through a real browser on the Mac mini, then commit + push.
# launchd com.jalal.reddit-browser (mac/com.jalal.reddit-browser.plist) runs this
# twice a day. It works in its OWN clone, never the working copy in
# ~/PycharmProjects, so it can't trip over half-done edits there.
# Everything sits inside main() so bash reads the whole file before
# `git reset --hard` below can rewrite it mid-run.
# Log: ~/Library/Logs/reddit-browser.log. Success line: "REDDIT PUSHED: N files".

main() {
  set -u
  export PATH="/opt/homebrew/bin:/usr/bin:/bin"
  local base="$HOME/.local/share/reddit-browser"
  local clone="$base/reddit-scraper"
  echo "== $(date) start"
  if [ ! -d "$clone/.git" ]; then
    git clone -q https://github.com/jalalchowdhury1/reddit-scraper.git "$clone" || { echo "clone failed"; return 1; }
  fi
  cd "$clone" || return 1
  git fetch -q origin main && git reset -q --hard origin/main || { echo "git sync failed"; return 1; }

  # -u: unbuffered, so a run killed by `timeout` still leaves its lines in the log.
  timeout 1200 /opt/homebrew/bin/python3 -u core/scrape_reddit_browser.py --profile "$base/profile"
  local rc=$?

  git add -f data/r_*/posts.csv
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
    git push -q origin HEAD:main && { ok=1; break; }
    git pull -q --rebase -X theirs origin main || git rebase --abort
    sleep 5
  done
  [ "$ok" = 1 ] || { echo "PUSH FAILED after 3 tries"; return 1; }
  echo "REDDIT PUSHED: $n files in $(git rev-parse --short HEAD)"
  echo "== $(date) done"
}

main "$@" >> "$HOME/Library/Logs/reddit-browser.log" 2>&1
