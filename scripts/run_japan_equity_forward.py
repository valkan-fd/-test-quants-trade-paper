#!/usr/bin/env python3
"""日本大型個別株版フォワード運用 — 米セクター → 日本個別株.

初期資金 ¥1,000,000 で毎営業日自動運用。
シグナル源: 米国セクターETF終値→終値
売買対象: 日本大型個別株（日経225 Large Cap）

cronで毎営業日 07:00 (日本株寄付前)に実行:
  0 7 * * 1-5 cd /path && python scripts/run_japan_equity_forward.py

用法:
  python scripts/run_japan_equity_forward.py \
    --source synthetic \
    --state state/japan_equity_forward.json \
    --initial 1000000 \
    --lam 0.9 \
    --factors 4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd

from src.config import StrategyConfig, JP_LARGE_CAP, US_SECTOR_ETFS
from src.data import get_data_source, MarketData
from src.forward_test import DailyForwardSimulator
from src.signal import StandardScaler, predict_next_day_jp
from src.pca import build_prior_subspace, subspace_regularized_pca


def create_hybrid_market_data(us_data: MarketData, jp_individual_returns: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """
    米セクターと日本個別株の結合データを作成。

    Parameters
    ----------
    us_data : 米国セクターETFデータ
    jp_individual_returns : {ticker: (T,) リターン配列}

    Returns
    -------
    (us_returns, jp_returns, jp_tickers) : (T, n_us), (T, n_jp), list
    """
    us_returns = us_data.us_cc.values
    jp_tickers = sorted(jp_individual_returns.keys())
    jp_returns = np.column_stack([jp_individual_returns[tk] for tk in jp_tickers])
    return us_returns, jp_returns, jp_tickers


def simulate_jp_individual_returns(data: MarketData, jp_tickers: list[str]) -> dict[str, np.ndarray]:
    """
    デモ用: 日本個別株リターンを合成データから生成。
    実運用ではyfinanceで実データを取得。
    """
    T = len(data.dates)
    rng = np.random.default_rng(42)
    returns = {}
    for tk in jp_tickers:
        # 簡略: セクター平均+アルファ のノイズで合成
        sector_beta = rng.uniform(0.5, 1.5)
        alpha_vol = 0.008
        returns[tk] = data.jp_oc.mean(axis=1).values * sector_beta + rng.standard_normal(T) * alpha_vol
    return returns


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default="synthetic", choices=["synthetic", "yfinance"])
    p.add_argument("--state", default="state/japan_equity_forward.json")
    p.add_argument("--initial", type=float, default=1_000_000.0)
    p.add_argument("--lam", type=float, default=0.9)
    p.add_argument("--factors", type=int, default=4)
    p.add_argument("--window", type=int, default=120)
    args = p.parse_args()

    cfg = StrategyConfig(lam=args.lam, n_factors=args.factors, window=args.window)
    src = get_data_source(args.source, **({} if args.source == "yfinance" else {"seed": cfg.seed}))
    data = src.load()

    # 日本個別株リターン取得（デモ版 or 実データ版）
    jp_tickers = list(JP_LARGE_CAP.keys())
    if args.source == "synthetic":
        jp_individual_returns = simulate_jp_individual_returns(data, jp_tickers)
        print(f"[データ] 合成データで日本大型株 {len(jp_tickers)} 銘柄をシミュレート")
    else:
        # 実運用: yfinanceで個別株を取得
        # jp_individual_returns = fetch_jp_individual_data(jp_tickers, ...)
        # → 実装は省略（yfinanceでティッカー別に download）
        raise NotImplementedError("実データ版は実装待ち。ローカルで yfinance を使用してください。")

    # 米セク × 日本個別株の結合相関モデル
    us_returns = data.us_cc.values
    jp_returns_array = np.column_stack([jp_individual_returns[tk] for tk in jp_tickers])

    T = len(data.dates)
    jp_cols = jp_tickers
    n_us = data.n_us
    n_jp = len(jp_tickers)

    if T < cfg.window + 2:
        print(f"[エラー] データ不足 ({T} < {cfg.window + 2})")
        return

    # 最新の予測可能日 (t+1が存在)
    t = T - 2
    date_exec = data.dates[t + 1]

    # 予測シグナル計算
    us_window = us_returns[t - cfg.window:t]
    jp_window_next = jp_returns_array[t - cfg.window + 1:t + 1]
    us_today = us_returns[t]

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

    # ペーパー運用
    sim = DailyForwardSimulator(args.state, initial_capital=args.initial)

    # 実現リターン
    realized = {jp_cols[i]: float(jp_returns_array[t + 1][i]) for i in range(len(jp_cols))}

    # ステップ実行
    log = sim.step(date_exec, {}, realized, cfg,
                   signal=pred, factor_scores=[float(f) for f in f_hat])
    sim.save()

    print(f"[OK] {log.date} を記録 (¥{log.equity:,.0f})")
    print(f"   Signal strength : {log.signal_strength:.6f}")
    print(f"   Net return      : {log.net_return*100:+.3f}%")
    print(f"   Turnover        : {log.turnover:.4f}")
    print(f"   Max position    : {log.max_pos} {log.max_pos_weight:+.4f}")
    print()
    print(sim.report())


if __name__ == "__main__":
    main()
