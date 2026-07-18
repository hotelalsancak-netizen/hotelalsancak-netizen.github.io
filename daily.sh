#!/usr/bin/env bash
# daily.sh — run the payment check for yesterday and leave an HTML report behind.
# Wire into cron (every morning at 09:00):
#   crontab -e
#   0 9 * * *  /home/work/Desktop/dev/rivacheck/daily.sh >> /home/work/Desktop/dev/rivacheck/daily.log 2>&1
set -uo pipefail
cd "$(dirname "$0")"

DATE="${1:-$(date -d yesterday +%F)}"
./.venv/bin/python paycheck.py --date "$DATE"
rc=$?

REPORT="reports/${DATE}.html"
echo "[$(date '+%F %T')] date=$DATE exit=$rc report=$REPORT"

# exit 1 means "unpaid reservations found" — not a crash. Anything >1 is a real failure.
if [ $rc -gt 1 ]; then
  echo "[$(date '+%F %T')] CHECK FAILED — no report produced, investigate." >&2
  exit $rc
fi

# Keep a stable path the browser can bookmark.
ln -sfn "${DATE}.html" reports/latest.html
exit 0
