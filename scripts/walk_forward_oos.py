#!/usr/bin/env python3
"""ウォークフォワード期間外(OOS)検証 — 論文の劣化を定量化.

用法:
  python scripts/walk_forward_oos.py --source synthetic \
    --train-window 252 --test-window 63 --step 63 \
    --outdir results/walk_forward

各期間のin-sample vs out-of-sample パフォーマンスを比較し、
過度な過最適化がないか、実データでの再現性があるかを検証する。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from src.config import StrategyConfig
from src.data import get_data_source
from src.forward_test import run_walk_forward


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--source", default="synthetic", choices=["synthetic", "yfinance"])
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--train-window", type=int, default=252)
    p.add_argument("--test-window", type=int, default=63)
    p.add_argument("--step", type=int, default=63)
    p.add_argument("--lam", type=float, default=0.9)
    p.add_argument("--factors", type=int, default=4)
    p.add_argument("--outdir", default="results/walk_forward")
    args = p.parse_args()

    cfg = StrategyConfig(lam=args.lam, n_factors=args.factors)
    src = get_data_source(args.source,
                          **({} if args.source == "yfinance"
                            else {"seed": cfg.seed}))
    data = src.load()

    print(f"[データ] {args.source} / {len(data.dates)} 営業日 "
          f"({data.dates[0].date()}〜{data.dates[-1].date()})")
    print(f"[設定] train_w={args.train_window} test_w={args.test_window} "
          f"step={args.step} lam={args.lam}\n")

    result = run_walk_forward(
        data, cfg,
        train_window=args.train_window,
        test_window=args.test_window,
        step=args.step,
    )

    print(result.summary())

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # 結果を JSON と CSV に保存
    wf_data = {
        "windows": [
            {
                "start_date": w.start_date,
                "end_date": w.end_date,
                "metrics": w.metrics,
                "n_trades": w.n_trades,
                "avg_turnover": w.avg_turnover,
            }
            for w in result.windows
        ],
        "overall_metrics": result.overall_metrics,
    }
    (outdir / "walk_forward_summary.json").write_text(
        json.dumps(wf_data, indent=2, ensure_ascii=False)
    )

    # 期間別メトリクスをCSV化
    window_records = []
    for w in result.windows:
        rec = {
            "start_date": w.start_date,
            "end_date": w.end_date,
            "annual_return": w.metrics["annual_return"],
            "annual_vol": w.metrics["annual_vol"],
            "sharpe": w.metrics["sharpe"],
            "max_drawdown": w.metrics["max_drawdown"],
            "hit_rate": w.metrics["hit_rate"],
            "n_trades": w.n_trades,
        }
        window_records.append(rec)

    if window_records:
        pd.DataFrame(window_records).to_csv(
            outdir / "walk_forward_periods.csv", index=False
        )
        print(f"[出力] {outdir}/walk_forward_summary.json")
        print(f"[出力] {outdir}/walk_forward_periods.csv")


if __name__ == "__main__":
    main()
