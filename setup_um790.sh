#!/usr/bin/env bash
# UM790 ワンコマンド・セットアップ
#
#   bash setup_um790.sh              # venv作成→依存導入→自己診断→cron行を表示
#   bash setup_um790.sh --install-cron  # 上記 + cron に自動登録（冪等）
#
# 目的: 「米セクターETF → 日本大型個別株」のフォワード・ペーパーテストを
#       UM790で毎営業日 自動実行できる状態にする（初期資金 ¥1,000,000）。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${REPO_DIR}"
INSTALL_CRON="no"
[ "${1:-}" = "--install-cron" ] && INSTALL_CRON="yes"

echo "================================================================"
echo " UM790 フォワード・ペーパーテスト セットアップ"
echo " リポジトリ: ${REPO_DIR}"
echo "================================================================"

# 1. Python 確認
if ! command -v python3 >/dev/null 2>&1; then
  echo "[NG] python3 が見つかりません。Python 3.11+ を導入してください。"; exit 1
fi
echo "[1/5] python3: $(python3 --version)"

# 2. venv 作成（既存ならスキップ）
if [ ! -d "venv" ]; then
  echo "[2/5] venv を作成中..."
  python3 -m venv venv
else
  echo "[2/5] venv は既に存在します。"
fi
# shellcheck disable=SC1091
source venv/bin/activate

# 3. 依存導入
echo "[3/5] 依存パッケージを導入中 (numpy/pandas/scipy/matplotlib/yfinance)..."
pip install -q --upgrade pip >/dev/null 2>&1 || true
pip install -q -r requirements.txt
echo "      導入完了。"

# 4. ディレクトリ
mkdir -p logs state results
chmod +x scripts/forward_cron.sh 2>/dev/null || true
echo "[4/5] logs/ state/ results/ を用意しました。"

# 5. 自己診断
echo "[5/5] 自己診断 (check_um790.py) を実行..."
echo "----------------------------------------------------------------"
set +e
python scripts/check_um790.py
CHECK_RC=$?
set -e
echo "----------------------------------------------------------------"

CRON_LINE="0 8 * * 1-5 ${REPO_DIR}/scripts/forward_cron.sh"
CRON_TZ_LINE="CRON_TZ=Asia/Tokyo"

echo ""
echo "■ cron 登録（毎営業日 08:00 JST に自動実行）"
echo "  以下2行を crontab に入れます（TZ明示が重要: UM790がUTC運用でも正しく動きます）:"
echo ""
echo "    ${CRON_TZ_LINE}"
echo "    ${CRON_LINE}"
echo ""

if [ "${INSTALL_CRON}" = "yes" ]; then
  # 冪等: 既に同じ行があれば追加しない
  CUR="$(crontab -l 2>/dev/null || true)"
  if echo "${CUR}" | grep -qF "${REPO_DIR}/scripts/forward_cron.sh"; then
    echo "  → 既に登録済みです。スキップしました。"
  else
    { echo "${CUR}"; echo "${CRON_TZ_LINE}"; echo "${CRON_LINE}"; } \
      | sed '/^$/d' | crontab -
    echo "  → crontab に登録しました。確認: crontab -l"
  fi
else
  echo "  自動登録するには: bash setup_um790.sh --install-cron"
fi

echo ""
if [ "${CHECK_RC}" -eq 0 ]; then
  echo "✅ 準備完了。まず手動で1回試す: "
  echo "   source venv/bin/activate && python scripts/run_japan_equity_forward.py --source yfinance"
  echo "   成績確認: python scripts/monitor_forward.py"
else
  echo "⚠️ 自己診断に未解決項目があります（多くは yfinance のネットワーク疎通）。"
  echo "   上の [NG] を解消してから cron 運用を開始してください。"
fi
