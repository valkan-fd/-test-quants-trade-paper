"""寄り引け（OPEN→CLOSE）戦略の設定。

バックテスト・フォワードテスト・フェッチで共有するパラメータを一元管理する。
"""
import os

# --- パス --------------------------------------------------------------------
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data", "jquantsapi", "v2")
PRICE_PATH = os.path.join(DATA_DIR, "stock_prices_mod.parquet")
LIST_PATH = os.path.join(DATA_DIR, "stock_list_mod.parquet")
ALERT_PATH = os.path.join(DATA_DIR, "margin_alert.parquet")

RESULTS_DIR = os.path.join(ROOT, "results")
STATE_DIR = os.path.join(ROOT, "state")
FORWARD_STATE_PATH = os.path.join(STATE_DIR, "oc_forward_state.json")
FORWARD_RETURNS_PATH = os.path.join(RESULTS_DIR, "oc_forward_returns.csv")
FORWARD_EQUITY_PNG = os.path.join(RESULTS_DIR, "oc_forward_equity.png")

# --- 結合キー ----------------------------------------------------------------
DATE_COL = "Date"
CODE_COL = "Code"

# --- ユニバース / 特徴量 ------------------------------------------------------
TOP_N = 20                      # 前日売買代金 上位N銘柄
FEATURES = ["OC", "ret1", "ret5", "ret21"]
ANALYSIS_YEARS = 10             # 分析期間（直近N年）

# --- 売買ルール --------------------------------------------------------------
# 売買方向: -1=逆張り（参考動画準拠）, +1=モメンタム
DIRECTION = -1
# フォワードテストで実際に建てるシグナル（FEATURES のいずれか）
SIGNAL_FEATURE = "ret5"
# 市況レジームフィルタ: "all"=常時, "up"=前日米国上昇のみ, "down"=前日米国下落のみ
MARKET_REGIME = "all"

# --- 市況特徴量（米国） ------------------------------------------------------
SP500_TICKER = "^GSPC"

# --- フォワードテスト --------------------------------------------------------
INITIAL_EQUITY = 1_000_000      # ペーパー口座の初期想定元本（指数表示用の基準）
