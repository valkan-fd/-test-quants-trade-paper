#!/usr/bin/env python
"""寄り引け戦略のバックテスト CLI（直近N年）。

  python scripts/run_oc_backtest.py

出力(results/): oc_backtest_feature_metrics.csv / oc_backtest_strategy_metrics.csv / oc_backtest_curves.png
S&P500 は yfinance で取得（要ネットワーク）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from oc_strategy import backtest, core, config as C  # noqa: E402


def main():
    price, stock_list, alert = core.load_inputs()
    start = (price[C.DATE_COL].min()).strftime("%Y-%m-%d")
    end = (price[C.DATE_COL].max()).strftime("%Y-%m-%d")
    sp = core.get_sp500_cc(start, end)
    panel = core.build_panel(price, stock_list, alert, sp)

    res = backtest.run(panel)
    print("=== 4特徴量 × 市況レジーム ===")
    print(res["feature_table"].to_string(index=False))
    print(f"\n=== 採用シグナル({C.SIGNAL_FEATURE}, dir={C.DIRECTION}, regime={C.MARKET_REGIME}) ===")
    for k, v in res["strategy_metrics"].items():
        print(f"  {k:12s}: {v}")
    print(f"\n対象営業日数: {res['n_dates']}  / 出力: {C.RESULTS_DIR}")


if __name__ == "__main__":
    main()
