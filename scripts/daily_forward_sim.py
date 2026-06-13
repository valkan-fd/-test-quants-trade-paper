#!/usr/bin/env python3
"""日次フォワードペーパー運用 — cronで毎営業日呼び出す.

用法:
  python scripts/daily_forward_sim.py --source synthetic --state state/forward_daily.json

状態は JSON に永続化され、毎日 append される。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.config import StrategyConfig
from src.data import get_data_source
from src.backtest import to_weights
from src.forward_test import DailyForwardSimulator
from src.signal import predict_next_day_jp_detailed


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="synthetic", choices=["synthetic", "yfinance"])
    p.add_argument("--state", default="state/forward_daily.json")
    p.add_argument("--lam", type=float, default=0.9)
    p.add_argument("--factors", type=int, default=4)
    p.add_argument("--window", type=int, default=120)
    args = p.parse_args()

    cfg = StrategyConfig(lam=args.lam, n_factors=args.factors, window=args.window)
    src = get_data_source(args.source)
    data = src.load()

    # 最新営業日の t を特定
    us = data.us_cc.values
    jp = data.jp_oc.values
    dates = data.dates
    T = len(dates)
    jp_cols = list(data.jp_oc.columns)

    if T < cfg.window + 2:
        print(f"[エラー] データが不足しています（{T} < {cfg.window + 2}）")
        return

    # 最新の「予測可能日」 t (翌日t+1が存在)
    t = T - 2
    date_exec = dates[t + 1]  # 寄りの建玉日

    # 予測 + 正規化ウェイト
    pred, f_hat, _ = predict_next_day_jp_detailed(
        us[t - cfg.window:t], jp[t - cfg.window + 1:t + 1], us[t],
        lam=cfg.lam, k=cfg.n_factors)
    w = to_weights(pred, cfg)

    # シミュレータ実行（冪等: 同じ日付は二重記録しない）
    sim = DailyForwardSimulator(args.state, initial_capital=1_000_000.0)
    if sim.last_date() is not None and str(date_exec.date()) <= sim.last_date():
        print(f"[情報] {date_exec.date()} は記録済みです（最終記録: {sim.last_date()}）。")
        print(sim.report())
        return

    weights = {jp_cols[i]: float(w[i]) for i in range(len(jp_cols))}
    realized = {jp_cols[i]: float(jp[t + 1][i]) for i in range(len(jp_cols))}
    log = sim.step(date_exec, weights, realized, cfg,
                   signal_strength=float(np.linalg.norm(pred)),
                   factor_scores=[float(f) for f in f_hat])
    sim.save()

    print(f"[OK] {log.date} を記録")
    print(f"   Signal strength: {log.signal_strength:.6f}")
    print(f"   Net return    : {log.net_return*100:+.3f}%")
    print(f"   Turnover      : {log.turnover:.4f}")
    print(f"   Max pos       : {log.max_pos} {log.max_pos_weight:+.4f}")
    print(sim.report())


if __name__ == "__main__":
    main()
