#!/usr/bin/env python3
"""ログのエクスポート — 戦略の「検証」と「再構築」のための分析可能形式に変換.

ペーパー運用の状態(state/japan_equity_forward.json)から、後で戦略を検証・再構築
できるだけの情報を持つエクスポート束を exports/ に生成する。GDrive へはこの
exports/ ディレクトリを丸ごと同期する(rclone 等)。

生成物:
  exports/
    forward_log_master.csv       # 全期間の日次ログ(累積・日付で重複排除)
    weights/weights_<date>.csv   # その日の全銘柄ウェイト(再構築用)
    snapshots/state_<date>.json  # 状態スナップショット(その時点の全ログ)
    run_metadata.json            # 再現に必要なパラメータ・ユニバース・gitハッシュ

「再構築」に必要な情報の考え方:
  予測の入力(米国/日本のリターン)は、日付さえあれば yfinance から再取得できる。
  したがって「日付 + パラメータ(λ/factors/window) + ユニバース + コード版(gitハッシュ)
  + 当日の予測ウェイト・実現リターン」を残せば、戦略を完全に再現・検証できる。

用法:
  python scripts/export_logs.py --state state/japan_equity_forward.json --outdir exports
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.config import JP_LARGE_CAP, US_SECTOR_ETFS, StrategyConfig


def git_hash() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[1], text=True).strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return os.environ.get("GIT_HASH", "unknown")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--state", default="state/japan_equity_forward.json")
    p.add_argument("--outdir", default="exports")
    p.add_argument("--lam", type=float, default=StrategyConfig.lam)
    p.add_argument("--factors", type=int, default=StrategyConfig.n_factors)
    p.add_argument("--window", type=int, default=StrategyConfig.window)
    args = p.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"[エラー] {state_path} が見つかりません。先にフォワード運用を実行してください。",
              file=sys.stderr)
        sys.exit(1)

    state = json.loads(state_path.read_text())
    logs = state.get("logs", [])
    if not logs:
        print("[情報] ログが空です。記録が貯まってから再実行してください。")
        return

    out = Path(args.outdir)
    (out / "weights").mkdir(parents=True, exist_ok=True)
    (out / "snapshots").mkdir(parents=True, exist_ok=True)

    # --- 1. 日次ログのマスターCSV(累積・重複排除) ---
    rows = []
    for lg in logs:
        rows.append({
            "date": lg["date"],
            "signal_strength": lg.get("signal_strength", 0.0),
            "gross_return": lg.get("realized_return", 0.0),
            "net_return": lg.get("net_return", 0.0),
            "turnover": lg.get("turnover", 0.0),
            "transaction_cost": lg.get("transaction_cost", 0.0),
            "equity": lg.get("equity", 0.0),
            "max_pos": lg.get("max_pos", ""),
            "max_pos_weight": lg.get("max_pos_weight", 0.0),
            "n_factors_logged": len(lg.get("factor_scores", [])),
        })
    df = pd.DataFrame(rows)
    master = out / "forward_log_master.csv"
    if master.exists():
        prev = pd.read_csv(master)
        df = pd.concat([prev, df]).drop_duplicates(subset=["date"], keep="last")
    df = df.sort_values("date").reset_index(drop=True)
    df.to_csv(master, index=False)

    # --- 2. 当日(最新ログ)の全銘柄ウェイト(再構築用) ---
    latest = logs[-1]
    latest_date = latest["date"]
    w = latest.get("weights", {})
    wdf = pd.DataFrame(
        [{"ticker": tk, "name": JP_LARGE_CAP.get(tk, ""), "weight": v}
         for tk, v in sorted(w.items(), key=lambda x: -abs(x[1]))])
    wdf.to_csv(out / "weights" / f"weights_{latest_date}.csv", index=False)

    # --- 3. 状態スナップショット ---
    (out / "snapshots" / f"state_{latest_date}.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2))

    # --- 4. 再現メタデータ ---
    meta = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "git_hash": git_hash(),
        "strategy": "US sector -> JP large-cap lead-lag (subspace-regularized PCA)",
        "params": {"lam": args.lam, "n_factors": args.factors, "window": args.window},
        "universe": {
            "us_sectors": list(US_SECTOR_ETFS.keys()),
            "jp_large_cap": list(JP_LARGE_CAP.keys()),
        },
        "initial_capital": state.get("initial_capital"),
        "current_equity": state.get("current_equity"),
        "n_days_logged": len(logs),
        "first_date": logs[0]["date"],
        "last_date": logs[-1]["date"],
    }
    (out / "run_metadata.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2))

    print(f"[OK] エクスポート完了 → {out}/")
    print(f"   forward_log_master.csv : {len(df)} 営業日(累積)")
    print(f"   weights/weights_{latest_date}.csv : {len(wdf)} 銘柄")
    print(f"   snapshots/state_{latest_date}.json")
    print(f"   run_metadata.json (git={meta['git_hash']}, "
          f"{meta['first_date']}〜{meta['last_date']})")


if __name__ == "__main__":
    main()
