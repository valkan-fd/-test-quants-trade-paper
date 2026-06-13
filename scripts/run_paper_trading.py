#!/usr/bin/env python3
"""ペーパーアカウント(仮想口座)運用スクリプト.

2通りの使い方:

  # (A) 過去 n 日を一括シミュレーション(デモ/検証)
  python scripts/run_paper_trading.py --mode simulate --days 60

  # (B) 日次ステップ(cron等で毎営業日呼ぶ。状態は state/ に永続化)
  python scripts/run_paper_trading.py --mode daily
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest import to_weights
from src.config import DEFAULT_CONFIG, StrategyConfig
from src.data import get_data_source
from src.paper_trading import PaperAccount, run_paper_simulation
from src.signal import predict_next_day_jp


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", default="simulate", choices=["simulate", "daily"])
    p.add_argument("--source", default="synthetic", choices=["synthetic", "yfinance"])
    p.add_argument("--days", type=int, default=60)
    p.add_argument("--initial", type=float, default=1_000_000.0)
    p.add_argument("--state", default="state/paper_account.json")
    p.add_argument("--no-reset", action="store_true")
    args = p.parse_args()

    cfg = StrategyConfig()
    src = get_data_source(args.source, **({} if args.source == "yfinance"
                                          else {"seed": cfg.seed}))
    data = src.load()

    if args.mode == "simulate":
        print(f"[ペーパー運用] 直近 {args.days} 営業日を仮想資金 "
              f"{args.initial:,.0f} 円でシミュレーション\n")
        acct = run_paper_simulation(
            data, cfg, state_path=args.state, n_days=args.days,
            initial_equity=args.initial, reset=not args.no_reset)
        print(acct.report())
        # 直近の建玉(発注プラン)を表示
        print("\n--- 最新営業日の目標ウェイト(翌寄りでリバランス) ---")
        for tk, w in sorted(acct.state.last_weights.items(),
                            key=lambda x: -abs(x[1])):
            if abs(w) > 1e-6:
                side = "LONG " if w > 0 else "SHORT"
                print(f"   {side} {tk:10s}: {w:+.4f}")
        return

    # daily モード: 最新営業日の予測を出し、1ステップだけ口座を進める
    acct = PaperAccount(args.state, initial_equity=args.initial)
    us = data.us_cc.values
    jp = data.jp_oc.values
    dates = data.dates
    Wn = cfg.window
    t = len(dates) - 2  # 最新の「予測可能日」
    jp_cols = list(data.jp_oc.columns)
    pred = predict_next_day_jp(us[t - Wn:t], jp[t - Wn + 1:t + 1], us[t],
                               lam=cfg.lam, k=cfg.n_factors)
    w = to_weights(pred, cfg)
    target = {jp_cols[i]: float(w[i]) for i in range(len(jp_cols))}
    realized = {jp_cols[i]: float(jp[t + 1][i]) for i in range(len(jp_cols))}
    rec = acct.step(dates[t + 1], target, realized, cfg.cost_bps)
    acct.save()
    print(f"[daily] {rec['date']} を記録: ret={rec['ret']*100:+.3f}% "
          f"turnover={rec['turnover']:.3f}")
    print(acct.report())


if __name__ == "__main__":
    main()
