#!/usr/bin/env python
"""寄り引け戦略の日次フォワードテスト（ペーパー運用）CLI。

毎営業日に 1 回（前日終値が取れた後＝当日寄り前 or 前日引け後）に実行する想定。
  1. scripts/fetch_jquants.py で parquet を更新してから
  2. python scripts/run_oc_forward.py

state(state/oc_forward_state.json) に進捗を永続化し、results/ に履歴 CSV と図を出力する。
S&P500 は yfinance で取得（要ネットワーク）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from oc_strategy import forward, config as C  # noqa: E402


def main():
    res = forward.run_once(write=True)
    print(f"実行時刻      : {res['ran_at']}")
    print(f"新規計上日数  : {res['new_days']}")
    print(f"最終計上日    : {res['last_decision_date']}")
    print(f"現在エクイティ: {res['equity']:.0f}  (初期 {C.INITIAL_EQUITY})")
    pend = res["state"].get("pending")
    if pend and pend.get("positions"):
        print(f"翌営業日の建玉(decision_date={pend['decision_date']}): "
              f"L={pend.get('n_long')} / S={pend.get('n_short')} / flat={pend.get('n_flat')}")
    print(f"出力: {C.FORWARD_RETURNS_PATH}")


if __name__ == "__main__":
    main()
