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
from src.forward_test import DailyForwardSimulator
from src.signal import predict_next_day_jp, StandardScaler
from src.pca import build_prior_subspace, subspace_regularized_pca


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
    t_latest = T - 2
    t = t_latest
    date_exec = dates[t + 1]  # 寄りの建玉日

    # 予測実行
    us_window = us[t - cfg.window:t]
    jp_window_next = jp[t - cfg.window + 1:t + 1]
    us_today = us[t]

    # シグナル計算（factorの詳細も抽出）
    n_us, n_jp = data.n_us, data.n_jp
    sc_us = StandardScaler().fit(us_window)
    sc_jp = StandardScaler().fit(jp_window_next)
    z_us = sc_us.transform(us_window)
    z_jp = sc_jp.transform(jp_window_next)
    joint = np.hstack([z_us, z_jp])
    prior = build_prior_subspace(n_us, n_jp)
    W, eigvals = subspace_regularized_pca(joint, prior, lam=cfg.lam, k=cfg.n_factors)
    W_us = W[:n_us, :]
    W_jp = W[n_us:, :]
    z_us_today = sc_us.transform(us_today.reshape(1, -1)).ravel()
    f_hat, *_ = np.linalg.lstsq(W_us, z_us_today, rcond=None)
    z_jp_pred = W_jp @ f_hat
    pred = sc_jp.inverse_std(z_jp_pred)

    # シミュレータ実行
    sim = DailyForwardSimulator(args.state, initial_capital=1_000_000.0)

    # 実現リターン（当日引けまで）
    realized = {jp_cols[i]: float(jp[t + 1][i]) for i in range(len(jp_cols))}

    # ステップ実行
    log = sim.step(date_exec, {}, realized, cfg,
                   signal=pred, factor_scores=[float(f) for f in f_hat])
    sim.save()

    print(f"[OK] {log.date} を記録")
    print(f"   Signal strength: {log.signal_strength:.6f}")
    print(f"   Net return    : {log.net_return*100:+.3f}%")
    print(f"   Turnover      : {log.turnover:.4f}")
    print(f"   Max pos       : {log.max_pos} {log.max_pos_weight:+.4f}")
    print(sim.report())


if __name__ == "__main__":
    main()
