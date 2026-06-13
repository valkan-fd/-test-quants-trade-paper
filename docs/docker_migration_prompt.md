# Docker ローカル運用 移行プロンプト（UKIさん日本株bot）

> 下の「==== プロンプト ====」以降を、**ローカル環境（UM790 / Windows + WSL2 + Docker Desktop）で開いた
> Claude Code セッション**にそのまま貼り付けて使う。クラウドのGitセッションではなく、Docker・ネットワーク・
> rclone・J-Quants認証情報が揃ったローカルで実行する前提。

---

==== プロンプト ====

あなたはこのリポジトリ（J-Quants ベースの「寄り引け（OPEN→CLOSE）戦略」プロジェクト）を、
**UM790（Windows 11 + WSL2 + Docker Desktop）上での Docker ローカル日次運用**に移行する作業を行う。
クラウド/Gitセッションでの実行をやめ、ローカルコンテナで毎営業日まわるようにするのが目的。

## 既存の構成（変更しないこと・前提）
- パッケージ `oc_strategy/`：`config.py / core.py / backtest.py / forward.py / sizing.py / data_fetch.py`
- スクリプト `scripts/`：`fetch_jquants.py`（J-Quants取得）, `run_oc_backtest.py`, `run_oc_longonly.py`,
  `run_oc_cost_compare.py`, `run_oc_forward.py`（A/B 2プロファイルの日次フォワード）, `make_sample_data.py`
- データ `data/jquantsapi/v2/*.parquet`、状態 `state/`、結果 `results/`、テスト `tests/`（pytest, 15件）
- フォワードは `forward.default_profiles()` の A_short_margin（単元+一日信用・両建）と
  B_mini_long（ミニ株・ロング専用・0円想定）を独立 state で並走。手数料・資金制約込みのネットで計上。
- S&P500 は yfinance、株価等は J-Quants（有料プラン＝前営業日まで）。TZは Asia/Tokyo。

## 作ってほしいもの
1. **Dockerfile**
   - ベース `python:3.11-slim`。`tzdata`（TZ=Asia/Tokyo）、日本語フォント `fonts-noto-cjk`（matplotlib文字化け対策）、
     `rclone`、`ca-certificates` を導入。
   - `pip install -r notebooks/requirements.txt`（pandas/numpy/matplotlib/pyarrow/yfinance/japanize-matplotlib/jupyterlab/jquants-api-client）。
   - 作業ディレクトリ `/app`、リポジトリをコピー。非rootユーザ推奨。
2. **docker-compose.yml**
   - サービス `bot`。`env_file: .env`。`environment: TZ=Asia/Tokyo`。
   - ボリューム（ホスト→コンテナ、データを永続化）:
     `./data:/app/data`, `./state:/app/state`, `./results:/app/results`, `./logs:/app/logs`,
     rclone設定 `~/.config/rclone/rclone.conf:/root/.config/rclone/rclone.conf:ro`。
   - 既定 `command` は日次スクリプト（下記）。長時間常駐ではなく **`docker compose run --rm bot` のワンショット運用**を基本にする。
3. **.dockerignore**（`.git`, `__pycache__`, `.venv`, `results/*.png` 等を除外。`data`は大きいので必要に応じ除外）
4. **.env.example**（コミット可。実 `.env` は .gitignore）
   ```
   JQUANTS_REFRESH_TOKEN=
   # もしくは JQUANTS_MAIL_ADDRESS= / JQUANTS_PASSWORD=
   CAPITAL=2000000
   RCLONE_REMOTE=gdrive
   GDRIVE_LOG_DIR=Claude/UKIさんの日本株bot提案
   ```
5. **scripts/daily_run.sh**（コンテナのエントリ。冪等・失敗時も続行しログ）
   - 手順：
     1. ログファイル `logs/oc_$(date +%Y%m%d_%H%M%S).log` に標準出力/エラーを tee。
     2. `python scripts/fetch_jquants.py --start 2014-01-01 --end $(date +%F)`（J-Quスタンダード以上・夜間配信後）。
     3. `python scripts/run_oc_forward.py --capital ${CAPITAL}`（A/B を1日前進。state永続で二重計上なし）。
     4. **毎週金曜など**は `run_oc_backtest.py` / `run_oc_longonly.py` / `run_oc_cost_compare.py` も実行し基準値更新。
     5. **rclone で GDrive へ同期**（同期先フォルダはrcloneが自動作成）:
        ```
        rclone copy /app/logs    "${RCLONE_REMOTE}:${GDRIVE_LOG_DIR}/logs"          --create-empty-src-dirs
        rclone copy /app/results "${RCLONE_REMOTE}:${GDRIVE_LOG_DIR}/results"
        rclone copy /app/state   "${RCLONE_REMOTE}:${GDRIVE_LOG_DIR}/state_backup"
        ```
   - Python側ログは `logging` で時刻・プロファイル・新規計上日数・エクイティ・翌日建玉(L/S)を構造化出力。
6. **rclone セットアップ手順**（READMEに記載）
   - ホスト(WSL2)で `rclone config` → Google Drive リモートを名前 `gdrive` で作成（OAuth）。
   - 同期先は `gdrive:Claude/UKIさんの日本株bot提案/`（このパスは初回 `rclone copy` で自動作成される）。
7. **スケジュール実行（Windows + WSL2）**
   - 推奨：**Windows タスクスケジューラ**から WSL を起動して one-shot 実行。
     プログラム `wsl.exe`、引数：
     ```
     -d Ubuntu -- bash -lc "cd ~/<repo> && docker compose run --rm bot bash scripts/daily_run.sh"
     ```
     トリガー：平日 19:00 JST（JPX株価配信後）。「スリープ解除して実行」を有効化。
   - 代替：コンテナ常駐＋`supercronic`/`cron` でも可。理由を添えて選定すること。
8. **ドキュメント更新** `docs/docker_local_ops.md`：ビルド/初回セットアップ/日次運用/ログのGDrive確認手順/トラブルシュート。
   既存 `docs/forward_test_um790.md` からDocker版へ誘導するリンクを追加。

## 制約・受け入れ条件
- 既存コードとテストを壊さない。**`docker compose run --rm bot pytest -q` が全green**。
- 秘密情報（`.env`, `rclone.conf`）は**コミットしない**（.gitignoreに追加）。`.env.example`のみコミット。
- TZ=Asia/Tokyo。matplotlib の日本語が文字化けしない（fonts-noto-cjk）。
- フォワードは state 永続で**何度実行しても二重計上しない**ことを確認（同日2回実行 → 2回目は新規0日）。
- 実データ（J-Quants）で `daily_run.sh` を1回通し、`logs/` と GDrive `Claude/UKIさんの日本株bot提案/logs` に
  ログが出る／`results/oc_forward_compare.png`（A vs B）が更新されることを確認。
- 完了後、変更内容と運用手順（毎日何が起きるか、ログの見方）を要約して報告する。

## 進め方
1. 上記ファイルを作成 → `docker compose build`。
2. まず同梱の合成サンプルデータ（`make_sample_data.py`）で `daily_run.sh` をドライラン（fetchはスキップ可能にし、
   `--no-fetch` 等のフラグを daily_run.sh に用意）。rclone も `--dry-run` で疎通確認。
3. 次に実 `.env`＋実データで本番フロー確認。
4. テスト緑・ドライラン成功を確認してから報告。不明点や判断が要る箇所は止めて質問すること。

==== プロンプトここまで ====

---

## 補足（このプロンプトの設計意図）
- **ワンショット運用（`docker compose run --rm`）** をデフォルトにしたのは、UM790のスリープ/再起動に強く、
  cron常駐より状態管理がシンプルなため。state/results/logs はホストにボリューム永続化されるので毎回引き継がれる。
- **rclone 同期**：`Claude/UKIさんの日本株bot提案/{logs,results,state_backup}` に蓄積。フォルダはrcloneが自動作成。
- **秘密情報は非コミット**：`.env` と `rclone.conf` は .gitignore。リポジトリには `.env.example` のみ。
- J-Quants は**スタンダード以上**（前営業日まで・10年）を想定。実行は**夜間の株価配信後**（例 19:00 JST）。
