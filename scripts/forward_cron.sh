#!/usr/bin/env bash
# UM790 フォワード・ペーパーテスト 日次実行ラッパー（cronから呼ぶ）。
#
# - 自身の位置からリポジトリルートを解決（cron の CWD に依存しない）
# - venv があれば自動で有効化
# - 米セクター → 日本個別株のフォワード運用を1ステップ実行
# - 標準出力/エラーを logs/ に追記
#
# crontab 例（タイムゾーンを明示するのが重要）:
#   CRON_TZ=Asia/Tokyo
#   0 8 * * 1-5 /abs/path/to/repo/scripts/forward_cron.sh
set -euo pipefail

# リポジトリルート = このスクリプトの1つ上
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_DIR}"

mkdir -p logs state

# venv があれば有効化（venv/ または .venv/）
if [ -f "venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
elif [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

PY="${PYTHON:-python3}"
STATE="${STATE_FILE:-state/japan_equity_forward.json}"
INITIAL="${INITIAL_CAPITAL:-1000000}"

TS="$(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "==================== ${TS} ====================" >> logs/daily_forward.log

# Python の失敗で即終了せず、終了コードを記録する
set +e
"${PY}" scripts/run_japan_equity_forward.py \
  --source yfinance \
  --state "${STATE}" \
  --initial "${INITIAL}" \
  >> logs/daily_forward.log 2>&1
RC=$?
set -e

echo "[done] exit=${RC} at ${TS}" >> logs/daily_forward.log
exit "${RC}"
