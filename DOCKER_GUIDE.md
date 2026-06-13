# Docker ローカル運用ガイド

「米セクター ETF → 日本大型個別株」のリードラグ戦略を Docker で **24h 自動運用**する手順。
ホスト側の cron 設定は不要。毎営業日 08:00 JST に自動実行。

---

## 1. ワンコマンド起動

```bash
docker-compose up -d
```

これだけで:
- Docker イメージをビルド
- `um790_forward_paper_test` コンテナを起動
- 毎営業日 08:00 JST に自動実行開始
- ログ・状態はホストの `logs/`, `state/`, `exports/` に保存

---

## 2. 動作確認

```bash
# コンテナのログをリアルタイム表示
docker logs -f um790_forward_paper_test

# コンテナの状態確認
docker ps | grep um790

# 実行ログ確認（ホストから）
tail -f logs/scheduler.log
```

期待される初回出力:
```
[INFO] UM790 Forward Paper Test Scheduler (Docker)
[INFO] Scheduler configured: Daily forward paper test (08:00 JST, weekdays only)
[INFO] Scheduler started. Press Ctrl+C to exit.
```

営業日の 08:00 JST になると自動実行が始まり、以下が記録されます：
```
[INFO] [START] Forward trading task at ...
[INFO] Running forward_test...
[INFO] forward_test OK: ...
[INFO] Exporting logs...
[INFO] [DONE] Forward task completed successfully
```

---

## 3. GDrive 同期（オプション）

ログを GDrive に自動蓄積する場合:

### 3.1 rclone セットアップ（1回だけ）

```bash
# rclone インストール
sudo apt install rclone  # or: curl https://rclone.org/install.sh | sudo bash

# Google Drive 認証
rclone config
# 選択: n)ew → 名前 gdrive → Google Drive
# ブラウザで認証 → コード入力
# フォルダ名: Claude/UKI論文改良bot
```

確認:
```bash
rclone lsf gdrive:Claude/UKI論文改良bot
```

### 3.2 docker-compose.yml に環境変数を追加

```yaml
environment:
  TZ: Asia/Tokyo
  GDRIVE_REMOTE: gdrive:Claude/UKI論文改良bot
```

または、起動時に指定:
```bash
GDRIVE_REMOTE="gdrive:Claude/UKI論文改良bot" docker-compose up -d
```

これで毎営業日の自動実行後、`exports/` と `logs/scheduler.log` が
`GDrive/Claude/UKI論文改良bot/` に自動同期されます。

---

## 4. 停止・再起動

```bash
# 停止
docker-compose down

# 再起動
docker-compose restart um790_forward_paper_test

# ログをクリアして新規開始
docker-compose down -v
docker-compose up -d
```

---

## 5. ローカル手動テスト

コンテナ外（ホスト側）で 1 回実行する場合:

```bash
# venv 有効化
source venv/bin/activate

# 手動実行
python scripts/run_japan_equity_forward.py --source yfinance

# 成績確認
python scripts/monitor_forward.py
```

---

## 6. トラブルシュート

| 症状 | 確認・対応 |
|---|---|
| コンテナが起動しない | `docker-compose logs` でエラー確認 |
| 08:00 に実行されない | `TZ=Asia/Tokyo` 設定確認 |
| yfinance がタイムアウト | ネット接続確認。コンテナ内: `ping 8.8.8.8` |
| GDrive 同期されない | `GDRIVE_REMOTE` 環境変数確認、`rclone lsf` でアクセス確認 |
| ログが肥大化 | `logs/` ディレクトリを定期削除（`docker-compose.yml` で `max-size` 指定済み） |

---

## 7. 本番運用チェックリスト

```
□ docker-compose up -d で起動確認
□ docker logs で "Scheduler started" を確認
□ 次営業日 08:00 JST の自動実行待機
□ docker logs -f で実行ログを監視
□ ホストの logs/scheduler.log にも記録されることを確認
□ export/ に weights_*.csv, run_metadata.json が生成されることを確認
```

GDrive 同期が必要なら:
```
□ rclone config で gdrive リモート設定
□ docker-compose.yml に GDRIVE_REMOTE 環境変数を追加
□ GDrive にエクスポート一式が同期されることを確認
```

---

## 8. イメージ再ビルド

コード更新後（`git pull` など）:

```bash
# イメージを再ビルド → コンテナ再起動
docker-compose up -d --build

# または
docker-compose down
docker-compose up -d
```

---

## 付録: docker-compose コマンド早見表

```bash
docker-compose up -d                              # バックグラウンド起動
docker-compose down                                # 停止・削除
docker-compose restart um790_forward_paper_test    # 再起動
docker-compose logs -f                             # リアルタイムログ
docker-compose ps                                  # ステータス確認
docker-compose exec um790_forward_paper_test bash  # コンテナにアクセス
```
