#!/usr/bin/env python3
"""バックテスト実行スクリプト.

使い方:
  # サンドボックス/合成データ(ネットワーク不要)
  python scripts/run_backtest.py --source synthetic

  # 実データ(ローカル・要 yfinance + ネットワーク)
  python scripts/run_backtest.py --source yfinance --start 2018-01-01
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.backtest import run_backtest, run_momentum_baseline
from src.config import DEFAULT_CONFIG, StrategyConfig
from src.data import get_data_source


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="synthetic", choices=["synthetic", "yfinance"])
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--lam", type=float, default=DEFAULT_CONFIG.lam)
    p.add_argument("--factors", type=int, default=DEFAULT_CONFIG.n_factors)
    p.add_argument("--window", type=int, default=DEFAULT_CONFIG.window)
    p.add_argument("--cost-bps", type=float, default=DEFAULT_CONFIG.cost_bps)
    p.add_argument("--variant", default="shrink", choices=["shrink", "penalty"])
    p.add_argument("--outdir", default="results")
    args = p.parse_args()

    cfg = StrategyConfig(lam=args.lam, n_factors=args.factors,
                         window=args.window, cost_bps=args.cost_bps)

    if args.source == "synthetic":
        src = get_data_source("synthetic", seed=cfg.seed)
        print("[データ] 合成データ(リードラグ構造を仕込んだ生成器)を使用")
    else:
        src = get_data_source("yfinance", start=args.start, end=args.end)
        print(f"[データ] yfinance 実データ {args.start}〜{args.end or '直近'}")

    data = src.load()
    print(f"[データ] 米国 {data.n_us} 業種 / 日本 {data.n_jp} 業種 / "
          f"{len(data.dates)} 営業日 ({data.dates[0].date()}〜{data.dates[-1].date()})")
    print(f"[設定] λ={cfg.lam} factors={cfg.n_factors} window={cfg.window} "
          f"cost={cfg.cost_bps}bps variant={args.variant}\n")

    res = run_backtest(data, cfg, variant=args.variant)
    base = run_momentum_baseline(data, cfg)

    print("===== 戦略: 部分空間正則化付きPCA リードラグ =====")
    print(res.summary())
    print("===== ベースライン: 単純モメンタム =====")
    print(base.summary())

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    res.daily_returns.to_csv(outdir / "strategy_returns.csv")
    res.equity_curve.to_csv(outdir / "strategy_equity.csv")
    pd.Series(res.metrics).to_csv(outdir / "strategy_metrics.csv")
    print(f"[出力] {outdir}/ に日次リターン・エクイティ・指標を保存")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))
        res.equity_curve.plot(ax=ax, label="Subspace-Reg PCA Lead-Lag")
        base.equity_curve.plot(ax=ax, label="Momentum baseline", alpha=0.7)
        ax.set_title("Equity Curve — US→JP Sector Lead-Lag (Subspace-Regularized PCA)")
        ax.set_ylabel("Growth of 1"); ax.legend(); ax.grid(alpha=0.3)
        fig.tight_layout(); fig.savefig(outdir / "equity_curve.png", dpi=120)
        print(f"[出力] {outdir}/equity_curve.png")
    except Exception as e:  # noqa
        print(f"[警告] プロット省略: {e}")


if __name__ == "__main__":
    main()
