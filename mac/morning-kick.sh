#!/bin/bash
# Daily Reader morning kick (28 Sep 2026). GitHub's own cron starts these jobs
# 2-4 h late, so the Mac mini starts them on time at 07:00, 08:30 and 10:00
# (com.jalal.daily-reader-kick). The GitHub cron lines stay as a backup.
# Log line per job: "KICK OK <workflow>" or "KICK FAILED <workflow>".
export PATH=/opt/homebrew/bin:/usr/bin:/bin
REPO=jalalchowdhury1/reddit-scraper
for wf in am_reads.yml github_trending.yml; do
  ok=0
  for i in 1 2 3; do
    gh workflow run "$wf" -R "$REPO" && { ok=1; break; }
    sleep 30
  done
  [ "$ok" = 1 ] && echo "$(date '+%F %T') KICK OK $wf" || echo "$(date '+%F %T') KICK FAILED $wf"
done
