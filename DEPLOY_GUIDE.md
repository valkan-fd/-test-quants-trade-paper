# UM790 フォワード・ペーパーテスト デプロイガイド

「**米セクターETF → 日本大型個別株**」のリードラグ戦略を、初期資金 **¥1,000,000** の
仮想口座で **毎営業日 自動** にペーパー運用（デモトレ）する手順。UM790 の既存 Docker
環境と干渉しない、ホスト側 cron 運用を前提とする。

> このペーパーテストの目的: 論文の手法（特にセクターETF版が「実際にダメか」）を、
> 流動性のある個別株へ応用したうえで前向きに検証し、実運用に値するか見極めること。

---

## 0. 仕組み（1日の流れ・JST）

```
~06:00  前夜の米国引けが確定（XLK等の終値→終値）→ シグナル算出
 08:00  cron が forward_cron.sh を実行
          ├─ まだ記録していない「確定済み営業日」を遡って約定・記録（冪等）
          └─ 「本日の発注プラン（目標ウェイト）」を表示
 09:00  （実運用時）日本株の寄りでリバランス（MOO）
 15:30  引けでエグジット（MOC）→ その日のP&Lが翌朝に確定・記録
```

毎日呼ぶだけで前向きにログ（`state/japan_equity_forward.json`）が積み上がる。
`step` は **正規化済みウェイト（グロス=1・ドルニュートラル）** で約定し、同じ日付を
二重記録しない（冪等）。

---

## 1. ワンコマンド・セットアップ

```bash
# リポジトリ取得
git clone https://github.com/valkan-fd/-test-quants-trade-paper.git
cd -test-quants-trade-paper
git checkout claude/friendly-pasteur-63lyv1

# venv作成 → 依存導入 → 自己診断 → cron行を表示
bash setup_um790.sh

# 問題なければ cron も自動登録
bash setup_um790.sh --install-cron
```

`setup_um790.sh` がやること:
1. `python3` 確認
2. `venv/` 作成（既存ならスキップ）
3. `requirements.txt`（**yfinance含む**）を導入
4. `logs/ state/ results/` 作成
5. `check_um790.py` で疎通確認 → cron 行を表示（`--install-cron` で登録）

---

## 2. 自己診断（最重要）

```bash
source venv/bin/activate
python scripts/check_um790.py
```

期待する結果（**すべて [OK] なら運用可能**）:

```
1. コア依存 (numpy/pandas/scipy)   [OK]
2. yfinance                         [OK]
3. 米国セクターETF取得              [OK]   ← UM790のネットがあれば成功
4. 日本個別株取得                   [OK]
5. 戦略パイプライン                 [OK]   gross=1.0, ドルニュートラル
```

> このサンドボックス（開発環境）では 3・4 が `Host not in allowlist`(403) で失敗します。
> これは開発環境固有のネットワーク制限で、**UM790（通常のネット環境）では起きません**。
> UM790 で 3・4 が `[OK]` になることだけ最初に必ず確認してください。

---

## 3. 手動テスト（cron前に1回）

```bash
source venv/bin/activate

# 1回実行（直近の確定日を記録 + 本日の発注プラン表示）
python scripts/run_japan_equity_forward.py --source yfinance

# もう一度（冪等性確認: 「新たに確定した営業日はありません」と出るはず）
python scripts/run_japan_equity_forward.py --source yfinance

# 成績ダッシュボード
python scripts/monitor_forward.py
```

---

## 4. cron 自動化（タイムゾーンに注意）

`setup_um790.sh --install-cron` を使わず手動で入れる場合:

```bash
crontab -e
```
以下の **2行** を追加:
```
CRON_TZ=Asia/Tokyo
0 8 * * 1-5 /絶対パス/-test-quants-trade-paper/scripts/forward_cron.sh
```

- **`CRON_TZ=Asia/Tokyo` が重要**: UM790 が UTC 運用でも 08:00 JST に正しく実行される
  （これが無いと、UTCマシンでは 08:00 UTC = 17:00 JST となり、日本市場の引け後に
  なってしまう）。
- **08:00 JST** にしている理由: 前夜の米国引け（~06:00 JST）が yfinance に取り込まれる
  余裕を取りつつ、日本市場の寄り（09:00）前に発注プランを得るため。
- `1-5` = 月〜金（祝日は別途。市場休場日はデータが増えないので冪等に無害）。

確認:
```bash
crontab -l
tail -f logs/daily_forward.log   # 実行ログ
```

---

## 5. Docker 併用について

既存 Docker が 24h 稼働中でも、本ペーパーテストは **ホスト側の軽量 cron** なので
干渉しない（数秒のPython実行が日1回だけ）。Docker内で動かしたい場合のみ、別コンテナ
＋ `forward_cron.sh` を使うが、通常はホスト cron で十分。

---

## 6. 日々の監視

```bash
python scripts/monitor_forward.py                 # サマリ表示
python scripts/monitor_forward.py --format csv     # CSV（表計算へ）
python scripts/monitor_forward.py --format json    # 機械可読
```

| 監視項目 | 正常 | 警告 | 対応 |
|---|---|---|---|
| Signal strength | > 0.1 | < 0.05 が継続 | 低波動。`--window` 拡大 / `--lam` 低下を検討 |
| Turnover | 0.5〜2 | 毎日 > 3 | 過回転。`--lam` を上げる |
| Daily net | ±0.3% | < -1% が3日連続 | DD注視。コスト設定確認 |
| Equity | 緩やか上昇 | peak比 -10% | パラメータ再検討 |

---

## 7. 実運用への分岐点（3ヶ月以上の観察後）

```
□ フォワードの平均 R/R ≥ 期間外OOS平均(≈2.3) × 70% ≈ 1.6
□ Deflation < 30%（過去検証からの減衰）
□ 最大DD < 15%
□ 実行コスト(turnover×bps) ≤ 期待α × 30%
```
満たせば、`src/paper_trading.py` の `BrokerAdapter` を国内証券API（例: kabu.com の
kabuステーションAPI）に実装して実発注へ。

---

## 8. トラブルシュート

| 症状 | 確認・対応 |
|---|---|
| cron が動かない | `crontab -l`、`grep CRON /var/log/syslog`、`CRON_TZ` 行の有無 |
| yfinance が空 | `python scripts/check_um790.py`、`pip install -U yfinance`、ネット/プロキシ |
| 8:00 に動くが日本株が古い | 祝日 or データ遅延。翌営業日に自動キャッチアップされる |
| ログが二重 | 冪等なので実害なし。同一日付は1回だけ記録される |

---

## 付録: 主要コマンド早見表

```bash
bash setup_um790.sh [--install-cron]                       # セットアップ
python scripts/check_um790.py                              # 自己診断
python scripts/run_japan_equity_forward.py --source yfinance  # 1日分の実行
python scripts/monitor_forward.py                          # 成績確認
python scripts/walk_forward_oos.py --source yfinance       # 期間外(OOS)検証
```
