#!/usr/bin/env python
"""端株(空売り不可)で long-only に変質したときの取り分を分析する CLI。

  python scripts/run_oc_longonly.py

出力(results/):
  - oc_side_decomposition.csv   : 特徴量 × 市況 × side(both/long/short) の指標
  - oc_longonly_best.csv        : long-only の SR 降順ランキング（端株の採用候補）
  - oc_longonly_curves.png      : long-only の4特徴量バランスカーブ（上昇=赤/下落=青）
S&P500 は yfinance で取得（要ネットワーク）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from oc_strategy import backtest, core, config as C  # noqa: E402


def main():
    price, stock_list, alert = core.load_inputs()
    sp = core.get_sp500_cc(price[C.DATE_COL].min().strftime("%Y-%m-%d"),
                           price[C.DATE_COL].max().strftime("%Y-%m-%d"))
    panel = core.build_panel(price, stock_list, alert, sp)
    sub = backtest.select_recent(panel)

    tbl = backtest.side_decomposition(sub)
    best = backtest.best_long_only(sub)

    os.makedirs(C.RESULTS_DIR, exist_ok=True)
    tbl.to_csv(os.path.join(C.RESULTS_DIR, "oc_side_decomposition.csv"), index=False)
    best.to_csv(os.path.join(C.RESULTS_DIR, "oc_longonly_best.csv"), index=False)
    backtest._plot_feature_grid(sub, os.path.join(C.RESULTS_DIR, "oc_longonly_curves.png"), side="long")

    show = ["feature", "regime", "side", "n_days", "ann_return", "sharpe", "max_dd", "win_rate"]
    print("=== side分解（両建 vs ロングのみ vs ショートのみ）===")
    print(tbl[show].round(3).to_string(index=False))
    print("\n=== long-only 採用候補（SR降順）===")
    print(best.round(3).to_string(index=False))
    if len(best):
        top = best.iloc[0]
        print(f"\n推奨(端株long-only): SIGNAL_FEATURE='{top.feature}', MARKET_REGIME='{top.regime}' "
              f"(SR={top.sharpe:.2f}, 年率={top.ann_return*100:.1f}%)")


if __name__ == "__main__":
    main()
