#!/usr/bin/env python
"""資金制約・手数料シナリオ比較 CLI。

理想（等加重・コスト無）に対し、単元/端株・各社手数料で純リターンがどれだけ目減りするかを比較する。
  python scripts/run_oc_cost_compare.py --capital 2000000

出力(results/): oc_cost_compare.csv / oc_cost_compare.png
⚠️ 手数料は既定の仮定値。oc_strategy/sizing.py の FEES を各社最新料金で要上書き。
S&P500 は yfinance で取得（要ネットワーク）。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from oc_strategy import core, sizing, config as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=int, default=C.CAPITAL)
    args = ap.parse_args()

    price, stock_list, alert = core.load_inputs()
    sp = core.get_sp500_cc(price[C.DATE_COL].min().strftime("%Y-%m-%d"),
                           price[C.DATE_COL].max().strftime("%Y-%m-%d"))
    panel = core.build_panel(price, stock_list, alert, sp)
    # 直近10年・ターゲット/市況が揃う行
    last = panel[C.DATE_COL].max()
    panel = panel[panel[C.DATE_COL] >= last - __import__("pandas").DateOffset(years=C.ANALYSIS_YEARS)]

    scenarios = sizing.default_scenarios(capital=args.capital)
    table, eq = sizing.compare(panel, scenarios)

    os.makedirs(C.RESULTS_DIR, exist_ok=True)
    table.to_csv(os.path.join(C.RESULTS_DIR, "oc_cost_compare.csv"), index=False)
    sizing.plot_equity(eq, os.path.join(C.RESULTS_DIR, "oc_cost_compare.png"))

    print(f"資金: {args.capital:,} 円 / シグナル: {C.SIGNAL_FEATURE} dir={C.DIRECTION} regime={C.MARKET_REGIME}")
    print(table.to_string(index=False))
    print(f"\n出力: {os.path.join(C.RESULTS_DIR, 'oc_cost_compare.csv')} / .png")
    print("※手数料は仮定値。sizing.FEES を各社最新料金で上書きのこと。")


if __name__ == "__main__":
    main()
