#!/usr/bin/env bash
# Fetch the upstream NSE end-of-day dataset used by this backtest.
#
# Source: https://github.com/BennyThadikaran/eod2_data
#   ~3,400 split/bonus-adjusted NSE equities, one CSV per symbol under daily/.
#
# A shallow clone is ~570 MB. After cloning, rebuild the weekly panel cache:
#   python src/data_loader.py eod2_data/daily --cache data/weekly --rebuild
#
# Note: the committed data/weekly.*.parquet cache already lets you run the
# backtest WITHOUT this download. Use this only to refresh or extend the data.
set -euo pipefail

DEST="${1:-eod2_data}"

if [ -d "$DEST/.git" ]; then
  echo "Updating existing clone at $DEST ..."
  git -C "$DEST" pull --depth 1 origin master
else
  echo "Shallow-cloning eod2_data into $DEST ..."
  git clone --depth 1 https://github.com/BennyThadikaran/eod2_data.git "$DEST"
fi

echo "Done. Rebuild the weekly cache with:"
echo "  python src/data_loader.py $DEST/daily --cache data/weekly --rebuild"
