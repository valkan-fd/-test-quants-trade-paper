# フォワードテスト・ガイド

## 概要

このドキュメントでは、論文の手法が実際に「稼ぐ」か、どの程度 degrade するか、
継続的に検証するための **フォワードテスト** の設計・運用方法を説明します。

### 2層構造

```
[1] ウォークフォワードOOS（過去データ）
    ├─ 複数年を train / test に分割
    ├─ 各期間で train → OOS test
    └─ In-Sample 過度な bias がないか判定 → 複数期間の平均R/R等で評価

[2] 日次ペーパー（前向き）
    ├─ 毎営業日 cron で実行
    ├─ 最新データ確認 → 寄りで仮想約定 → 引けでマーク
    └─ JSON に日次ログ＆詳細指標を蓄積（戦略改善の素地）
```

---

## 1. ウォークフォワードOOS（`walk_forward_oos.py`）

### 仕組み

2018〜2023年のデータを、1年 train + 3ヶ月 test のブロックで逐次スライド：

```
[Train: 252日] [Test: 63日] → 記録 → スライド
             [Train: 252日] [Test: 63日] → 記録 → ...
```

各 test ブロックは **学習後に見えるデータのみ** 使用 → 真の期間外(OOS)評価。

### 実行

```bash
python scripts/walk_forward_oos.py \
  --source synthetic \
  --train-window 252 \
  --test-window 63 \
  --step 63 \
  --outdir results/walk_forward

# 実データ版（ローカル）
python scripts/walk_forward_oos.py \
  --source yfinance \
  --start 2018-01-01 \
  --train-window 252 \
  --test-window 63
```

### 出力

`results/walk_forward/` に以下を保存：

| ファイル | 内容 |
|---|---|
| `walk_forward_summary.json` | 全期間の統計（平均R/R等） |
| `walk_forward_periods.csv` | 期間別メトリクス |

### 結果解釈

```
期間別パフォーマンス:
  2018-01〜2019-03: 年率  9.85% R/R= 1.40
  2019-12〜2021-02: 年率 15.08% R/R= 3.22
  2021-11〜2023-01: 年率 25.49% R/R= 5.67
  ...
全体平均: R/R = 2.87（論文報告 2.22 に近い）
```

**判断基準**:
- ✅ 平均R/R が論文の 2.22 に近い（±20% 程度が許容）
- ⚠️  期間別で 3〜5倍の差がある場合 → regime dependency あり（市場環境に敏感）
- ❌ OOS R/R が IS R/R から 50% 以上低下 → 過度な curve fitting 疑い

---

## 2. 日次ペーパー運用（`daily_forward_sim.py`）

### 仕組み

毎営業日、cronで以下を実行：

1. 最新データ確認（前営業日までの米国セクターETF＆日本個別株）
2. 過去120営業日の結合相関で PCA モデルを更新
3. 当日米国終値 → 翌日日本リターン を予測
4. **翌営業日 寄り(09:00)** で仮想約定
5. **引け(15:30)** でマーク→ JSON に記録

### 実行（単発）

```bash
python scripts/daily_forward_sim.py --source synthetic --state state/forward_daily.json
```

### 実行（自動化 / cron）

```bash
# /etc/cron.d/forward-test  または crontab -e に追加
# 平日 07:00 に実行（日本株寄付前）
0 7 * * 1-5 cd /path/-test-quants-trade-paper && \
  python scripts/daily_forward_sim.py \
  >> logs/daily_forward.log 2>&1
```

### 出力ファイル

`state/forward_daily.json` — 永続状態（JSON）:

```json
{
  "initial_capital": 1000000,
  "current_equity": 1002456,
  "last_weights": {
    "1621.T": 0.0234,
    "1632.T": -0.0187,
    ...
  },
  "logs": [
    {
      "date": "2023-09-29",
      "signal_strength": 0.401,
      "net_return": 0.00047,
      "turnover": 0.169,
      "equity": 1000465,
      "max_pos": "1621.T",
      "max_pos_weight": 0.0232,
      ...
    }
  ]
}
```

### ログの見方

```python
import json
with open('state/forward_daily.json') as f:
    data = json.load(f)

# 直近10営業日の P&L
logs = data['logs'][-10:]
for log in logs:
    print(f"{log['date']}: {log['net_return']*100:+.3f}% "
          f"(equity={log['equity']:,.0f})")

# 月次の集計
import pandas as pd
df = pd.DataFrame(logs)
df['date'] = pd.to_datetime(df['date'])
monthly = df.set_index('date').resample('M')['net_return'].apply(
    lambda x: ((1 + x).prod() - 1) if len(x) > 0 else 0
)
print(monthly)
```

### 監視項目

| 項目 | 正常 | 警告 | アクション |
|---|---|---|---|
| **Signal Strength** | > 0.1 | < 0.05 | 市場が低波動→シグナルが消えている。モデル更新確認 |
| **Turnover** | 0.1〜0.5 | > 1.5 | 過度なリバランス。λを上げる / window を伸ばす |
| **Net Return(日単位)** | ±0.3% | < -1% 連続3日 | ドローダウン警告。コスト増加の可能性確認 |
| **Equity 成長** | 緩やか上昇 | 3ヶ月で -10% | 戦略が機能していない。パラメータ再調整 |

---

## 3. 統合ワークフロー

### Step 1: オフラインで OOS 検証（デプロイ前）

```bash
# 1〜2年の過去データで十分な R/R が出ているか確認
python scripts/walk_forward_oos.py --source yfinance --outdir results/oos_check
# → walk_forward_periods.csv で期間別の stability を確認
```

### Step 2: ペーパー前向き開始（本番環境へ deploy）

```bash
# UM790 に daily cron 登録
# 数週間〜数ヶ月のペーパー実行で：
#   - 実際の市場で signal が出ているか
#   - OOS 予測精度と forward のズレはどの程度か
#   - 実行コスト（turnover × bps）が許容範囲か
```

### Step 3: デフレーション分析

数ヶ月の forward ログが溜まったら：

```python
# forward_daily.json から期間別 Sharpe を算出
# OOS average Sharpe (2.87) vs forward observed Sharpe
# の ratio = deflation factor

# 例: forward で observed R/R = 1.5 が、OOS 2.87 だった場合
# deflation = 1.5 / 2.87 = 52%
# → データ期間依存性 + 実行 slippage 込みで半減している
# → acceptable か unacceptable か判断
```

### Step 4: 実運用へ（オプション）

forward P&L が安定したら、**実ブローカーAPI** に接続：

```python
# src/paper_trading.py の BrokerAdapter を国内証券API（例：kabu.com）に実装
# 数百万円の初期資金で運用開始
```

---

## 4. 実装の詳細（ユーザー向け）

### A. 米セクターETF + 日本個別株の混合版

現在の実装（日本セクターETF）から「稼ぐ版」へ移行する際：

**変更点**:

```python
# 現在: jp_oc は日本セクターETF（17銘柄）
# 新規: jp_universe は日経225 large cap（～100銘柄）
#       → 流動性向上、キャパシティ拡大、実行可能

# signal generation は同じ
pred = predict_next_day_jp(us_window, jp_window_next, us_today)

# ポートフォリオ構築で sector mapping を追加
# 予測シグナルを「sector」から「individual stock」に拡張
```

実装例は `src/signal.py` の `predict_next_day_jp` 関数を参考。

### B. パラメータチューニング

forward log から以下を監視して調整：

| パラメータ | 増やすと | 減らすと | 基準 |
|---|---|---|---|
| **λ (正則化強度)** | signal 削減 | 不安定化 | daily turnover 監視 |
| **window (学習期間)** | 推定安定 | lag 増加 | 3〜6ヶ月が目安 |
| **factors (因子数)** | flexible | noise 削減 | 3〜5 推奨 |
| **cost_bps (コスト)** | 保守的 | 楽観的 | 実際の往復コスト入力 |

---

## 5. FAQ

**Q. OOS R/R が in-sample より大きく出ることはある？**

A. あります。特に短期間で lucky period に当たる場合。ただし複数期間の平均では in-sample ≥ out-of-sample になるのが通常。「複数期間の OOS 平均」が判断軸。

**Q. daily forward で信号が出なくなった場合？**

A. 市場が低波動。signal_strength < 0.05 が続く場合、window を伸ばす・λを減らす・因子数を増やす を試す。ただしテスト期間中は手を入れず、ログを貯める。

**Q. 実運用への分岐点は？**

A. 
- forward R/R が OOS 平均の **70% 以上** 出た（deflation < 30%）
- **3〜6ヶ月** のペーパーで positive
- 実行コスト（turnover × bps）が期待αの **30% 以下**

これら満たしたら検討。

---

## 6. 参考

- 論文: [部分空間正則化付き主成分分析を用いた日米業種リードラグ投資戦略](https://www.jstage.jst.go.jp/article/jsaisigtwo/2026/FIN-036/2026_76/_article/-char/ja/)
- スマート投資チャンネル解説動画: 本人の8年運用トラックレコード＆論文の位置付けを説明
- 手法の元祖は個別株＆流動性のある市場への応用が本命（セクターETFは検証用）
