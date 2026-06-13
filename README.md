# UM790 Forward Paper Test
**「米セクター ETF → 日本大型個別株」リードラグ戦略の自動ペーパーテスト**

---

## 概要

UKI 論文（*Subspace-Regularized PCA for US-Japan Sector Lead-Lag Investment Strategy*）の手法を実装し、
初期資金 **¥1,000,000** で毎営業日 自動運用・検証するシステム。

**主な特徴:**
- ✅ **因果的バックテスト**: 当日の米国セクター終値 → 翌営業日の日本株予測
- ✅ **ドルニュートラル**: グロス=1.0、ロング・ショートバランス済み
- ✅ **完全再現性**: git ハッシュ + パラメータ + ユニバース + 実現値を記録
- ✅ **3つの運用方式**: 開発用（synthetic） / 本番 Git（ホスト cron） / **Docker ローカル（推奨）**

---

## クイックスタート

### 🐳 Docker ローカル運用（WSL/Mac/Linux）— **推奨**

```bash
# リポジトリ取得
git clone https://github.com/valkan-fd/-test-quants-trade-paper.git
cd -test-quants-trade-paper

# 起動（自動的に毎営業日 08:00 JST に実行開始）
docker-compose up -d

# ログ確認
docker logs -f um790_forward_paper_test
```

**→ 詳細は [DOCKER_GUIDE.md](DOCKER_GUIDE.md)**

---

### 🖥️ Git ホスト cron 運用（UM790）

```bash
# ワンコマンド・セットアップ（venv + 依存 + cron 登録）
bash setup_um790.sh --install-cron

# 自動実行開始（毎営業日 08:00 JST）
tail -f logs/daily_forward.log
```

**→ 詳細は [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md)**

---

### 🧪 開発・テスト（Synthetic Data）

```bash
# venv 作成 → 依存導入
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# バックテスト実行（ネットワーク不要）
python scripts/walk_forward_oos.py --source synthetic

# 成績確認
python scripts/monitor_forward.py
```

---

## ファイル構成

```
.
├── README.md                          ← このファイル
├── DEPLOY_GUIDE.md                    ← Git ホスト cron 運用ガイド（UM790向け）
├── DOCKER_GUIDE.md                    ← Docker ローカル運用ガイド（推奨）
│
├── Dockerfile                         ← Docker イメージ定義
├── docker-compose.yml                 ← Docker Compose 設定
├── .dockerignore                      ← Docker ビルド除外
│
├── setup_um790.sh                     ← Git 運用のワンコマンド・セットアップ
├── requirements.txt                   ← Python 依存（yfinance, apscheduler 含む）
│
├── src/
│   ├── __init__.py
│   ├── config.py                      ← 戦略パラメータ（λ、ウィンドウ、ユニバース）
│   ├── data.py                        ← yfinance / synthetic データローダー
│   ├── pca.py                         ← Subspace-Regularized PCA 実装
│   ├── signal.py                      ← 予測シグナル（因果・OOS検証）
│   ├── backtest.py                    ← バックテスト実行・ウェイト正規化
│   └── forward_test.py                ← フォワード・ペーパーテスト（冪等ログ）
│
├── scripts/
│   ├── check_um790.py                 ← 自己診断（依存・ネット疎通確認）
│   ├── run_japan_equity_forward.py    ← フォワード・ペーパーテスト実行（1日分）
│   ├── export_logs.py                 ← ログをエクスポート・再構築可能形式に変換
│   ├── monitor_forward.py             ← 成績ダッシュボード
│   ├── walk_forward_oos.py            ← Out-of-Sample 検証
│   │
│   ├── forward_cron.sh                ← Git 運用: cron ラッパー（venv + 実行 + export + rclone）
│   └── daily_scheduler.py             ← Docker 運用: APScheduler スケジューラー
│
├── tests/
│   ├── __init__.py
│   └── test_strategy.py               ← 回帰テスト（3項目）
│
├── state/
│   └── japan_equity_forward.json       ← フォワード・ペーパーテストログ（冪等）
│
├── logs/
│   ├── daily_forward.log              ← Git 運用ログ
│   └── scheduler.log                  ← Docker 運用ログ
│
├── exports/                           ← 検証・再構築用エクスポート束
│   ├── forward_log_master.csv         ← 日次マスター（累積・重複排除）
│   ├── weights_*.csv                  ← 当日のウェイト（全銘柄）
│   ├── snapshots/state_*.json         ← 状態スナップショット
│   └── run_metadata.json              ← gitHash + パラメータ + ユニバース
│
└── results/                           ← バックテスト結果（図表等）
```

---

## 運用方式の選び方

| 目的 | 方式 | 起動コマンド | 自動実行 | 必須環境 |
|---|---|---|---|---|
| **開発・バグチェック** | Synthetic | `python scripts/walk_forward_oos.py --source synthetic` | なし | Python 3.11+ |
| **本番・UM790** | Git cron | `bash setup_um790.sh --install-cron` | 毎営業日 08:00 JST（ホスト cron） | Python + cron |
| **ローカル PC（WSL/Mac）** | **Docker** | `docker-compose up -d` | 毎営業日 08:00 JST（コンテナ APScheduler） | Docker |

---

## コア実装

### 1. 戦略パラメータ（`src/config.py`）

```python
class StrategyConfig:
    lam: float = 0.9              # Shrinkage パラメータ（0=PCA, 1=等重）
    n_factors: int = 3            # 使用因子数
    window: int = 252             # ローリング学習ウィンドウ（営業日）
```

**US セクター ETF（11 種類）:**
- XLK (IT), XLV (Healthcare), XLY (Consumer Disc.), XLP (Consumer Staples)
- XLI (Industrials), XLE (Energy), XLRE (Real Estate), XLU (Utilities)
- XLF (Financials), XLB (Materials)

**日本大型個別株（51 種類）:**
- TOPIX100/JPIX200 から選定（流動性高い銘柄）

### 2. 因果的バックテスト（`src/backtest.py` + `src/signal.py`）

```
[t-252, t) : 学習ウィンドウ
    ↓
Subspace-Regularized PCA
    ↓
t日の米国セクター（close-to-close）
    ↓
予測 → (t+1)日の日本株リターン（open-to-close）
    ↓
(t+1)日に実現値と照合
    ↓
因果関係を検証（t日の情報のみ使用）
```

### 3. フォワード・ペーパーテスト（`src/forward_test.py`）

- **冪等性**: 同一日付は 1 回だけ記録（`last_date()` チェック）
- **正規化**: gross = 1.0、ドルニュートラル（mean = 0）
- **ログ形式**: JSON（再構築可能。gitHash + パラメータ + ウェイト + 実現値）

```json
{
  "date": "2026-06-13",
  "signal_strength": 0.234,
  "realized_return": 0.0012,
  "net_return": 0.0010,
  "turnover": 0.85,
  "equity": 1010000,
  "weights": { "6758.T": 0.05, "8008.T": -0.03, ... }
}
```

### 4. エクスポート・再構築（`scripts/export_logs.py`）

毎営業日の実行後、以下を自動生成:

- **forward_log_master.csv** - 全期間の日次ログ（累積・重複排除）
- **weights_YYYY-MM-DD.csv** - 当日のウェイト（全銘柄）
- **snapshots/state_YYYY-MM-DD.json** - 状態スナップショット
- **run_metadata.json** - gitHash + パラメータ + ユニバース

**→ 日付 + git ハッシュ + パラメータがあれば yfinance から再取得可能**

---

## 主要コマンド

```bash
# 1. 自己診断（依存・ネット疎通）
source venv/bin/activate
python scripts/check_um790.py

# 2. 手動テスト（実データ 1 回実行）
python scripts/run_japan_equity_forward.py --source yfinance

# 3. Out-of-Sample 検証（6ヶ月チャレンジ）
python scripts/walk_forward_oos.py --source yfinance --start 2026-01-01

# 4. 成績ダッシュボード
python scripts/monitor_forward.py
python scripts/monitor_forward.py --format csv    # 表計算用
python scripts/monitor_forward.py --format json   # 機械可読

# 5. 回帰テスト
python -m pytest tests/test_strategy.py -v
```

---

## 技術スタック

- **Python 3.11+** (numpy, pandas, scipy, scikit-learn)
- **yfinance** - 米国 ETF / 日本株の実時間データ取得
- **APScheduler** - Docker 内の自動実行スケジューラー
- **rclone** - GDrive への自動同期
- **Docker / Docker Compose** - コンテナ化・本番運用

---

## トラブルシュート

### yfinance が 403 エラー（sandbox 環境）

**原因:** このリポジトリを開発・テストしているサンドボックス環境がネット制限中。

**対応:** 
- **本番環境（UM790/WSL）では起きません** ← 正常なネット環境
- sandbox では `--source synthetic` を使ってテスト
- `python scripts/walk_forward_oos.py --source synthetic` で確認可

---

## 参考資料

| ドキュメント | 対象 | 内容 |
|---|---|---|
| [DEPLOY_GUIDE.md](DEPLOY_GUIDE.md) | UM790 ホスト運用 | cron 設定、rclone/GDrive、トラブルシュート |
| [DOCKER_GUIDE.md](DOCKER_GUIDE.md) | Docker ローカル運用 | docker-compose、ログ確認、GDrive 同期 |
| `src/config.py` | 戦略設定 | パラメータ（λ, window）、ユニバース |
| `tests/test_strategy.py` | テスト | 3つの回帰テスト（形状・正規化・因果性） |

---

## ライセンス・参考論文

UKI 論文:  
*Subspace-Regularized PCA for US-Japan Sector Lead-Lag Investment Strategy*

実装: valkan-fd  
初期資本: ¥1,000,000 (paper trading)

---

**重要:** 開発環境では `--source synthetic` でテスト。本番環境（UM790/WSL）では `--source yfinance` で運用。3ヶ月以上のフォワード検証後、実運用への分岐を検討してください。
