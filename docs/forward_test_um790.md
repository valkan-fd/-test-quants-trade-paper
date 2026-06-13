# 寄り引け戦略 フォワードテスト運用ガイド（UM790 / Windows + WSL2）

UM790（Windows + WSL2）上で、寄り引け戦略を **毎営業日ペーパー運用** し、
バックテストの期待値と突き合わせて「使える戦略か」を検証するための手順。

```
取得(J-Quants) ─▶ data/jquantsapi/v2/*_mod.parquet ─▶ バックテスト(基準値)
                                                  └▶ フォワードテスト(日次・state永続化)
```

---

## 0. 前提：データ取得プラン（重要）

| プラン | 月額 | データ期間 | 遅延 | フォワードテスト |
|---|---|---|---|---|
| 無料 | 0円 | 2年 | **12週遅延** | ❌ 不可（前日終値が取れない） |
| ライト | 1,650円 | 5年 | 前営業日まで | ✅ 可 |
| スタンダード | 3,300円 | 10年 | 前営業日まで | ✅ 可（**10年BTも揃うので推奨**） |
| プレミアム | 16,500円 | 無制限 | 前営業日まで＋前場四本値 | ✅ 可 |

> 直近10年バックテストの基準値まで自前で揃えるなら **スタンダード(3,300円/月)** が無難。
> 日次バッチは株価配信（夜間）の後に実行すること。

- 寄り引け運用は「**前日引け後に判断 → 翌寄りで建て → 引けで決済**」なので、毎朝“前営業日まで”のデータが必須。
- **無料プランでは forward test は成立しない**。まずは有料プラン契約が前提。
- プラン仕様・価格は変わるため、契約前に J-Quants 公式で現行仕様を必ず確認すること。

### 売り禁（`RestrictedByJSF`）について
信用区分（`Mrgn`）は上場銘柄一覧から取れるが、売り禁は **日本証券金融(JSF) の貸借取引規制（申込停止/注意喚起）** 由来。
J-Quants のどのエンドポイントに対応するか未確定のため、`oc_strategy/data_fetch.py::fetch_short_restriction`
は **未結線（規制なし扱い）のスタブ**。実ソース（JSF公表データ等）を確定したらここを埋める。
結線するまでは「売り禁による空売り除外」が効かない点に注意。

---

## 1. セットアップ（WSL2 / Ubuntu）

```bash
# WSL2 の Ubuntu 内で
sudo apt update && sudo apt install -y python3-venv
git clone <this repo> && cd <repo>
git switch claude/quirky-brahmagupta-302jnl

python3 -m venv .venv && source .venv/bin/activate
pip install -r notebooks/requirements.txt
pip install jquants-api-client     # 取得に必要
```

### 認証情報（環境変数）
`~/.bashrc` などに：
```bash
export JQUANTS_REFRESH_TOKEN="（J-Quants のリフレッシュトークン）"
# もしくは
# export JQUANTS_MAIL_ADDRESS="you@example.com"
# export JQUANTS_PASSWORD="********"
```

---

## 2. 初回：実データ取得 → バックテスト基準値

```bash
# 1) 実データ取得（合成サンプルを上書き）
python scripts/fetch_jquants.py --start 2014-01-01 --end $(date +%F)

# 2) バックテスト（直近10年の基準値）
python scripts/run_oc_backtest.py
```
出力（`results/`）:
- `oc_backtest_feature_metrics.csv` … 4特徴量 × 市況レジームの指標（動画の図に対応）
- `oc_backtest_strategy_metrics.csv` … 採用シグナルの年率/SR/最大DD/勝率
- `oc_backtest_curves.png` … バランスカーブ4枚

> 採用シグナルや方向は `oc_strategy/config.py` の `SIGNAL_FEATURE` / `DIRECTION` / `MARKET_REGIME` で変更。
> 既定は `ret5` / 逆張り(-1) / 全レジーム。バックテストを見て決めること。

---

## 3. 日次：フォワードテスト（毎営業日 1 回）

```bash
python scripts/fetch_jquants.py --start 2014-01-01 --end $(date +%F)   # データ更新
python scripts/run_oc_forward.py --capital 2000000                     # A/B 両方を1ステップ前進
```
**2方式を同時にペーパー検証**（`oc_strategy/forward.py::default_profiles`）：
- `A_short_margin`：単元＋一日信用（両建＝ショート可）。戦略フル。
- `B_mini_long`：ミニ株/端株（ロング専用・0円想定）。多銘柄分散。

いずれも **手数料・資金制約込みのネットリターン**（`sizing.py`）で積み上げる。各プロファイルは
`state/oc_forward_<name>.json` に独立永続化（**二重計上なし**）。
出力：`results/oc_forward_<name>.csv`／`.png`、比較図 `results/oc_forward_compare.png`。
実行ログに各方式の「翌営業日の建玉（L/S 数）」も表示（B はショート0）。

> プロファイルの採用シグナル/レジームは `config.py` の `SIGNAL_FEATURE`/`MARKET_REGIME`、
> 資金・手数料は `--capital` と `sizing.FEES`/`default_profiles` で調整。
> A は `run_oc_backtest.py`、B は `run_oc_longonly.py` の結果から最適を選ぶ。

### 仕組み（リーク防止）
1. **判断**：最新の完了日 `t`（前日引け後に確定）でユニバース・特徴量を計算し、翌日 `t+1` の建玉を `pending` に保存。
2. **実現**：`t+1` の寄り・引けが確定したら `Target = C/O-1` を計上し、エクイティを更新。

決定→結果が別実行に分かれるので、毎日回せば本物の前向き検証になる。

---

## 4. スケジュール実行

東京市場は 15:30 引け。**引け後（例: 平日 18:00 JST）** に 1 回回すのが基本。
S&P500 前日終値は `yfinance` で都度取得（要ネットワーク）。

### A. WSL2 の cron（推奨）
```bash
sudo service cron start                 # WSL2 では手動起動が要る場合あり
crontab -e
```
```cron
# 平日 18:00 JST に取得→フォワード（WSLのTZをAsia/Tokyoに）
0 18 * * 1-5 cd /home/<user>/<repo> && . .venv/bin/activate && \
  python scripts/fetch_jquants.py --start 2014-01-01 --end $(date +\%F) >> logs/fetch.log 2>&1 && \
  python scripts/run_oc_forward.py >> logs/forward.log 2>&1
```
> WSL2 はシャットダウンで cron が止まる。常時起動なら `wsl --exec` をWindowsのタスクで起こすか、systemd 有効化(`/etc/wsl.conf` の `[boot] systemd=true`)＋ `systemd timer` を使う。

### B. Windows タスクスケジューラから WSL を叩く
「プログラム」に `wsl.exe`、引数：
```
-d Ubuntu -- bash -lc "cd ~/<repo> && . .venv/bin/activate && python scripts/fetch_jquants.py --end $(date +%F) && python scripts/run_oc_forward.py"
```
トリガー：平日 18:00。PCがスリープでも起きるよう「タスクの実行時にスリープを解除」を有効化。

---

## 5. 「使える戦略か」の見方
- フォワードのエクイティ（`oc_forward_equity.png`）が、バックテストの期待 SR/年率と **同程度のスロープ** で伸びているか。
- 大きく下振れ・横ばいなら、レジーム変化／過学習／実行コスト未考慮が疑われる。
- **未考慮の現実コスト**：手数料・スリッページ・寄り引けの約定可能性・板の薄さ。動画でも「実際はSRが半分かも」と言及。
- **資金制約**：200万では値がさ株の100株が買えず、毎日20銘柄均等は非現実的（動画 L290-301）。実運用は銘柄数・サイズの制約を別途モデル化する。

---

## 6. 注意
- リポジトリ同梱の `data/jquantsapi/v2/*.parquet` は **合成サンプル**。`fetch_jquants.py` で実データに上書きするまで、結果に意味はない。
- 本コードは研究・検証用。投資勧誘ではなく、将来の成果を保証しない。
