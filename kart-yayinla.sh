#!/usr/bin/env bash
# Haftalık kart güvenliği yayını (yerel).
#
# Önce kilit PDF'lerini cardreads/<GGAAYYYY>/ içine koyun ve occupancy.json'u
# güncelleyin (python3 elektra_api.py --occupancy <FROM> <TO>). Sonra bu betiği
# çalıştırın: kart raporunu üretir, ŞİFRELER, repoya push eder ve buluttaki
# dashboard'u yeniden yayınlar.
set -euo pipefail
cd "$(dirname "$0")"

# .env'den DASH_PASSWORD + GITHUB_TOKEN yükle.
set -a; source .env; set +a
: "${DASH_PASSWORD:?.env içinde DASH_PASSWORD yok}"
: "${GITHUB_TOKEN:?.env içinde GITHUB_TOKEN yok}"
export GH_TOKEN="$GITHUB_TOKEN"

PY="${PYTHON:-python3}"
REPO="hotelalsancak-netizen/hotelalsancak-netizen.github.io"

echo "1/3  Kart bölümü üretiliyor + şifreleniyor..."
"$PY" dashboard.py --cards

echo "2/3  site_data/kart.enc.json push ediliyor..."
git add site_data/kart.enc.json
git commit -q -m "Kart güvenliği: haftalık güncelleme ($(date +%d.%m.%Y))" || {
  echo "   (değişiklik yok — yine de yayın tetiklenecek)"; }
git push -q "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git" HEAD:main

echo "3/3  Bulut yayını tetikleniyor..."
gh workflow run dashboard.yml -R "$REPO"
echo "Bitti. Birkaç dakika içinde dashboard güncellenir:"
echo "  https://hotelalsancak-netizen.github.io/"
