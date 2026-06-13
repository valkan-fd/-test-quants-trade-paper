#!/usr/bin/env python
"""寄り引け戦略の日次フォワードテスト（ペーパー運用）CLI。A/B 両方式を同時に検証。

毎営業日に 1 回（前営業日の株価が配信された夜以降）に実行する想定。
  1. scripts/fetch_jquants.py で parquet を更新してから
  2. python scripts/run_oc_forward.py [--capital 2000000]

並走プロファイル:
  A_short_margin : 単元+一日信用（両建＝ショート可）
  B_mini_long    : ミニ株/端株（ロング専用・0円想定）

各プロファイルは state/oc_forward_<name>.json に永続化（二重計上なし）。
出力: results/oc_forward_<name>.csv/.png と比較図 oc_forward_compare.png。
S&P500 は yfinance で取得（要ネットワーク）。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from oc_strategy import forward, config as C  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=int, default=C.CAPITAL)
    args = ap.parse_args()

    res = forward.run_all(write=True, capital=args.capital)
    print(f"実行時刻: {res['ran_at']}  / 資金: {args.capital:,} 円\n")
    for name, r in res.items():
        if name == "ran_at":
            continue
        st = r["state"]
        print(f"[{name}] 新規計上 {r['new_days']}日 / 最終 {r['last_decision_date']} / "
              f"エクイティ {r['equity']:,.0f} 円")
        pend = st.get("pending") or {}
        if pend.get("positions") is not None:
            print(f"   翌営業日の建玉(decision={pend.get('decision_date')}): "
                  f"L={pend.get('n_long')} / S={pend.get('n_short')}")
    print(f"\n出力: {C.RESULTS_DIR}/oc_forward_*.csv|.png, oc_forward_compare.png")


if __name__ == "__main__":
    main()
