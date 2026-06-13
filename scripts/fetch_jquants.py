#!/usr/bin/env python
"""J-Quants から price/list/売り禁 を取得して data/jquantsapi/v2/ に保存する CLI。

使い方:
  export JQUANTS_REFRESH_TOKEN=xxxx      # もしくは JQUANTS_MAIL_ADDRESS / JQUANTS_PASSWORD
  python scripts/fetch_jquants.py --start 2014-01-01 --end 2026-06-12

⚠️ 有料プラン（ライト以上）が前提。売り禁(RestrictedByJSF)は data_fetch.fetch_short_restriction の
   結線が必要（未結線だと規制なし扱い）。
"""
import argparse
import datetime as dt
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from oc_strategy import data_fetch  # noqa: E402


def main():
    today = dt.date.today()
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=str(today.replace(year=today.year - 12)))
    ap.add_argument("--end", default=str(today))
    args = ap.parse_args()
    data_fetch.save_all(args.start, args.end)


if __name__ == "__main__":
    main()
