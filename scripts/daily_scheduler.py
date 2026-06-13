#!/usr/bin/env python3
"""毎営業日 08:00 JST にペーパーテスト自動実行（Docker 内スケジューラー）.

APScheduler で以下の定期タスクを管理:
  1. 毎営業日 08:00 JST: run_japan_equity_forward.py を実行
  2. 同じタイミング: export_logs.py を実行（エクスポート生成）
  3. 同じタイミング: rclone で exports/ をGDriveに同期（GDRIVE_REMOTE設定時）

使用法:
  # Docker 内で自動実行（Dockerfile CMD）
  python scripts/daily_scheduler.py

  # ホストから起動
  docker-compose up -d
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/scheduler.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

REPO_DIR = Path(__file__).resolve().parents[1]
os.chdir(REPO_DIR)


def run_forward_task() -> None:
    """毎営業日 08:00 JST に実行: フォワード・ペーパーテスト + エクスポート + GDrive同期."""
    ts = datetime.now(timezone.utc).isoformat()
    logger.info(f"[START] Forward trading task at {ts}")

    try:
        # 1. フォワード・ペーパーテスト実行
        logger.info("Running forward_test...")
        result = subprocess.run(
            [
                sys.executable,
                "scripts/run_japan_equity_forward.py",
                "--source", "yfinance",
                "--state", "state/japan_equity_forward.json",
                "--initial", "1000000",
            ],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(f"forward_test failed: {result.stderr}")
        else:
            logger.info(f"forward_test OK: {result.stdout[:200]}")

        # 2. ログエクスポート
        logger.info("Exporting logs...")
        result = subprocess.run(
            [sys.executable, "scripts/export_logs.py", "--state", "state/japan_equity_forward.json", "--outdir", "exports"],
            cwd=REPO_DIR,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            logger.error(f"export_logs failed: {result.stderr}")
        else:
            logger.info(f"export_logs OK: {result.stdout[:200]}")

        # 3. GDrive同期（GDRIVE_REMOTE設定時）
        gdrive_remote = os.getenv("GDRIVE_REMOTE")
        if gdrive_remote and _has_command("rclone"):
            logger.info(f"Syncing to GDrive: {gdrive_remote}")
            result = subprocess.run(
                ["rclone", "copy", "exports", f"{gdrive_remote}/exports"],
                cwd=REPO_DIR,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.warning(f"rclone exports sync failed: {result.stderr}")
            else:
                logger.info(f"rclone exports sync OK")

            result = subprocess.run(
                ["rclone", "copy", "logs/scheduler.log", f"{gdrive_remote}/logs/"],
                cwd=REPO_DIR,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                logger.warning(f"rclone logs sync failed: {result.stderr}")
            else:
                logger.info(f"rclone logs sync OK")
        else:
            if not gdrive_remote:
                logger.info("GDRIVE_REMOTE not set, skipping GDrive sync")
            if not _has_command("rclone"):
                logger.warning("rclone not found, skipping GDrive sync")

        logger.info(f"[DONE] Forward task completed successfully")

    except Exception as e:
        logger.error(f"[ERROR] Forward task failed: {e}", exc_info=True)


def _has_command(cmd: str) -> bool:
    """Check if command exists in PATH."""
    try:
        subprocess.run(["which", cmd], capture_output=True, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def main() -> None:
    logger.info("=" * 70)
    logger.info("UM790 Forward Paper Test Scheduler (Docker)")
    logger.info("=" * 70)
    logger.info(f"Repository: {REPO_DIR}")
    logger.info(f"Working directory: {os.getcwd()}")

    # 初期ディレクトリ作成
    Path("logs").mkdir(exist_ok=True)
    Path("state").mkdir(exist_ok=True)
    Path("results").mkdir(exist_ok=True)
    Path("exports").mkdir(exist_ok=True)

    # APScheduler 設定
    scheduler = BackgroundScheduler()

    # 毎営業日 08:00 JST (JST = UTC+9)
    # APScheduler の day_of_week は月=0, 日=6
    # 1-5 = 月〜金 (営業日)
    scheduler.add_job(
        run_forward_task,
        trigger=CronTrigger(
            hour=8,
            minute=0,
            second=0,
            day_of_week="mon-fri",
            timezone="Asia/Tokyo",
        ),
        id="forward_task",
        name="Daily forward paper test (08:00 JST, weekdays only)",
        replace_existing=True,
    )

    logger.info("Scheduler configured:")
    for job in scheduler.get_jobs():
        logger.info(f"  {job.name}: {job.trigger}")

    scheduler.start()
    logger.info("Scheduler started. Press Ctrl+C to exit.")

    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down scheduler...")
        scheduler.shutdown()
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
