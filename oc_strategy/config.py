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
# 売買方向: -1=逆張り（参考動画準拠・画像の全曲線が正→逆張りで確定）, +1=モメンタム
DIRECTION = -1
# フォワードテストで実際に建てるシグナル（FEATURES のいずれか）
# 画像より: OC は両レジームで安定(SR~1.2)。ret1/ret5 は米国下落の翌日に限り強い(SR1.16/1.45)。
SIGNAL_FEATURE = "OC"
# 市況レジームフィルタ: "all"=常時, "up"=前日米国上昇のみ, "down"=前日米国下落のみ
# 例) 高SR狙いは SIGNAL_FEATURE="ret5" + MARKET_REGIME="down"。全天候は "OC"+"all"。
MARKET_REGIME = "all"

# 参照画像（YouTube）の凡例値。実データ実行時の較正チェック用。
#   feature: {regime: (日数, 累積cumsum, SR)}
REFERENCE_LEGEND = {
    "OC":    {"up": (1352, 0.631, 1.16), "down": (1068, 0.581, 1.29)},
    "ret1":  {"up": (1352, 0.067, 0.12), "down": (1068, 0.581, 1.16)},
    "ret5":  {"up": (1352, 0.052, 0.09), "down": (1068, 0.731, 1.45)},
    "ret21": {"up": (1352, 0.322, 0.53), "down": (1068, 0.095, 0.19)},
}

# --- 市況特徴量（米国） ------------------------------------------------------
SP500_TICKER = "^GSPC"

# --- フォワードテスト --------------------------------------------------------
INITIAL_EQUITY = 1_000_000      # ペーパー口座の初期想定元本（指数表示用の基準）

# --- 資金制約・コスト比較（sizing.py） ---------------------------------------
CAPITAL = 2_000_000             # 想定運用資金（動画準拠 200万円）
UNIT_SHARES = 100               # 単元株数
