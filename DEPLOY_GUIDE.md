# UM790でのフォワード運用デプロイガイド

初期資金 **¥1,000,000** で日本大型個別株のペーパー運用を、
UM790マシンの既存Docker環境に統合して、毎営業日 07:00 に自動実行。

---

## 1. 前提条件・環境確認

### 既存構成
- UM790 マシン（Linux/Ubuntu）
- Docker で別プログラムが 24h 稼働中
- Python 3.11+、pip が使用可能
- ネットワーク接続あり（market data 取得）

### 新規構成
```
UM790
├─ 既存 Docker Container A（24h稼働中）
└─ 新規 cron job: run_japan_equity_forward.py
   ├─ 毎営業日 07:00 実行
   └─ state/japan_equity_forward.json に累積ログ
```

---

## 2. インストール・セットアップ

### Step 1: リポジトリを UM790 にクローン

```bash
cd /path/to/your/projects
git clone https://github.com/valkan-fd/-test-quants-trade-paper.git
cd -test-quants-trade-paper

# または、既に clone されている場合は pull
git fetch origin
git checkout claude/friendly-pasteur-63lyv1
git pull origin claude/friendly-pasteur-63lyv1
```

### Step 2: 仮想環境（推奨）or グローバル環境で依存インストール

```bash
# 仮想環境利用の場合
python3 -m venv venv
source venv/bin/activate

# 依存インストール
pip install -r requirements.txt

# 実データ取得用（yfinance）— 必須
pip install yfinance
```

### Step 3: ディレクトリ・状態ファイル初期化

```bash
mkdir -p state logs results
touch state/.gitkeep

# 初期状態ファイルを手動作成（初回のみ）
python3 << 'EOF'
import json
initial_state = {
    "initial_capital": 1000000.0,
    "current_equity": 1000000.0,
    "last_weights": {},
    "logs": []
}
with open("state/japan_equity_forward.json", "w") as f:
    json.dump(initial_state, f, indent=2)
print("[OK] state/japan_equity_forward.json を初期化")
EOF
```

---

## 3. ローカルテスト（デプロイ前に必須）

### 合成データで動作確認

```bash
# 1回実行
python scripts/run_japan_equity_forward.py \
  --source synthetic \
  --state state/test_local.json \
  --initial 1000000

# ダッシュボード確認
python scripts/monitor_forward.py --state state/test_local.json
```

期待される出力:
```
[OK] YYYY-MM-DD を記録 (¥1000XXXX)
   Signal strength : 0.4xxxxx
   Net return      : +0.0xx%
フォワード運用ダッシュボード
初期資金          : ¥1,000,000
現在評価額        : ¥1,000,XXX
...
```

### 実データで動作確認（推奨・ネットワーク要）

```bash
# 過去1ヶ月のデータで本番同様に実行
python scripts/run_japan_equity_forward.py \
  --source yfinance \
  --state state/test_yfinance.json \
  --initial 1000000 \
  --lam 0.9

# 複数日続けてテスト（翌営業日に再実行確認）
python scripts/run_japan_equity_forward.py \
  --source yfinance \
  --state state/test_yfinance.json

# ダッシュボード
python scripts/monitor_forward.py --state state/test_yfinance.json
```

問題が出た場合の checklist:
- [ ] `yfinance` が米セクターETF（XLB等）を取得できるか
- [ ] `yfinance` が日本株（7203.T等）を取得できるか
- [ ] `state/test_*.json` に ログが蓄積されているか
- [ ] Signal strength > 0.05 （市場が生きているか）

---

## 4. cron 自動化設定

### Step 1: cron ジョブを登録

```bash
# crontab を編集
crontab -e

# 以下を追加（毎営業日 07:00 実行）
0 7 * * 1-5 cd /path/to/-test-quants-trade-paper && \
  source venv/bin/activate 2>/dev/null && \
  python scripts/run_japan_equity_forward.py \
  --source yfinance \
  --state state/japan_equity_forward.json \
  --initial 1000000 \
  >> logs/daily_forward.log 2>&1

# 保存 & 確認
crontab -l | grep run_japan_equity
```

### Step 2: ログローテーション設定

```bash
# /etc/logrotate.d/um790-forward-test を作成
cat > /tmp/um790-forward-test << 'EOF'
/path/to/-test-quants-trade-paper/logs/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
}
EOF

# 確認（sudo 必要）
sudo cp /tmp/um790-forward-test /etc/logrotate.d/
sudo logrotate -v /etc/logrotate.d/um790-forward-test
```

### Step 3: cron 実行確認

```bash
# cron のジョブ実行結果を監視
tail -f /var/log/syslog | grep CRON

# または、手動で次の営業日を待たずにテスト
# (cron 本番環境での動作確認)
at now + 2 minutes << 'EOF'
cd /path/to/-test-quants-trade-paper && \
  source venv/bin/activate && \
  python scripts/run_japan_equity_forward.py \
  --source yfinance \
  >> logs/test_at.log 2>&1
EOF
```

---

## 5. Docker 統合（既存コンテナとの共存）

既存の Docker でプログラムが 24h 稼働している場合、
新規 cron ジョブを ホスト側で実行（軽量・干渉なし）するのが推奨。

### 代替案: Docker Compose で統合運用したい場合

```yaml
# docker-compose.yml 例
version: "3.9"
services:
  existing_bot:
    # ... 既存コンテナ定義
    environment:
      - TZ=Asia/Tokyo

  forward_test:
    image: python:3.11
    working_dir: /app
    volumes:
      - .:/app
      - ./state:/app/state
      - ./logs:/app/logs
    environment:
      - TZ=Asia/Tokyo
    command: |
      /bin/bash -c "
      pip install -q -r requirements.txt &&
      python scripts/run_japan_equity_forward.py \
        --source yfinance \
        --state /app/state/japan_equity_forward.json
      "
    restart: "no"
    depends_on:
      - existing_bot

  # cron 代わりに APScheduler で定期実行する場合
  scheduler:
    image: python:3.11
    working_dir: /app
    volumes:
      - .:/app
      - ./state:/app/state
      - ./logs:/app/logs
    environment:
      - TZ=Asia/Tokyo
    command: python scripts/scheduler_runner.py
    restart: always
    depends_on:
      - forward_test
```

ただし、**単純な cron ジョブで十分** な場合が多い。Docker 統合は必須でなければスキップ推奨。

---

## 6. 日次監視・運用オペレーション

### 毎日チェックすべき項目

```bash
# ダッシュボード確認（毎朝、寄り後に）
python scripts/monitor_forward.py --state state/japan_equity_forward.json

# CSV で月次レポート生成
python scripts/monitor_forward.py --state state/japan_equity_forward.json \
  --format csv > results/daily_forward_latest.csv

# ログ確認
tail logs/daily_forward.log
```

### 警告・アラート基準

| 監視項目 | 正常 | 警告 | アクション |
|---|---|---|---|
| **Signal Strength** | > 0.1 | < 0.05 連続3日 | モデル更新 / λ調整 |
| **Daily Return** | ±0.3% | < -1% 連続3日 | ドローダウン注視 |
| **Equity** | 上昇トレンド | -10% from peak | コスト/パラメータ見直し |
| **Turnover** | 0.1~0.5 | > 1.0 毎日 | window 拡大 / λ増加 |

### 月次レビュー（毎月末）

```bash
# 月間 Sharpe, Deflation 分析
python scripts/monitor_forward.py \
  --state state/japan_equity_forward.json \
  --format json > results/monthly_review.json

# エクセルで可視化 (CSV export)
python scripts/monitor_forward.py \
  --format csv >> results/daily_logs_archive.csv
```

---

## 7. 実運用への分岐点（目安）

forward ペーパー運用が以下を **3ヶ月以上** 満たしたら実運用検討：

```
□ 平均 R/R ≥ OOS平均(2.87) × 70% = 2.0
□ Deflation < 30%（初期パフォーマンスの減衰許容）
□ 最大DD < 15%（ロスカット基準はここを下回らない）
□ 実行コスト（turnover×bps）≤ 期待α × 30%
□ 市場regime に関わらず安定（Sharpe 標準偏差 < 1.0）
```

達成時:

```bash
# 実ブローカー API に接続（実装例）
# src/paper_trading.py の BrokerAdapter を国内証券API（例: kabu.com）に実装

# 実運用開始
python scripts/run_japan_equity_live.py \
  --broker kabu \
  --api-key YOUR_API_KEY \
  --account ACCOUNT_ID \
  --initial-capital 1000000
```

---

## 8. トラブルシューティング

### Q. cron が実行されない

```bash
# ① crontab に登録されているか確認
crontab -l

# ② シェルスクリプトパスが正しいか
which python3

# ③ cron ログで実行状況確認
grep CRON /var/log/syslog | tail -20

# ④ 手動で cron コマンド実行テスト
cd /path/to/-test-quants-trade-paper && \
  source venv/bin/activate && \
  python scripts/run_japan_equity_forward.py --source yfinance
```

### Q. Signal Strength が < 0.05 で消えている

```bash
# ① データを確認（市場が低波動か）
python3 << 'EOF'
import yfinance as yf
import pandas as pd
us_data = yf.download(['XLB'], period='5d')['Close'].pct_change().dropna()
print(f"米国セクター直近ボラ: {us_data.std():.4f}")
EOF

# ② λ を下げる / window を伸ばす / factors を増やす
python scripts/run_japan_equity_forward.py \
  --source yfinance \
  --state state/test_params.json \
  --lam 0.7 --window 180 --factors 5
```

### Q. yfinance でデータが取得できない

```bash
# ① ネットワーク疎通確認
ping -c 1 query1.finance.yahoo.com

# ② yfinance をアップグレード
pip install --upgrade yfinance

# ③ プロキシ経由が必要か確認
# → UM790 ネットワーク管理者に確認
```

---

## 9. 参考リンク

- **GitHub リポジトリ**: https://github.com/valkan-fd/-test-quants-trade-paper
- **論文**: [部分空間正則化付きPCA日米業種リードラグ投資戦略](https://www.jstage.jst.go.jp/article/jsaisigtwo/2026/FIN-036/2026_76/)
- **スマート投資チャンネル**: 手法の元祖による解説＆8年運用トラックレコード
- **yfinance ドキュメント**: https://yfinance.readthedocs.io/

---

## 10. サポート・質問

問題が発生した場合:

1. `logs/daily_forward.log` でエラーメッセージ確認
2. `scripts/monitor_forward.py` で最新P&L確認
3. `state/japan_equity_forward.json` の logs 配列でシグナル強度確認
4. テスト用の `--source synthetic` で既知の動作確認

---

## チェックリスト（デプロイ前）

- [ ] Python 3.11+、pip インストール確認
- [ ] requirements.txt から依存インストール完了
- [ ] yfinance で米国セクターETF取得確認
- [ ] yfinance で日本株取得確認
- [ ] `scripts/run_japan_equity_forward.py --source synthetic` で動作確認
- [ ] `state/japan_equity_forward.json` 初期化完了
- [ ] crontab 登録確認
- [ ] `logs/daily_forward.log` ディレクトリ存在確認
- [ ] ログローテーション設定完了
- [ ] 既存Docker等との干渉なし確認

✅ すべてチェック完了 → **本番デプロイ Go!**

