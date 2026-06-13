#!/usr/bin/env python3
"""日本大型個別株版フォワード・ペーパー運用 — 米セクター → 日本個別株.

初期資金 ¥1,000,000 で毎営業日に呼び出す前向きペーパー運用。
シグナル源: 米国セクターETF 終値→終値（前夜の米国引け）
売買対象  : 日本大型個別株（始値→終値）

タイミング(JST):
  ~06:00  前夜の米国引けが確定 → シグナル算出
   09:00  日本株の寄りで建玉（MOO）
   15:30  引けでエグジット（MOC）→ その日のP&Lが確定

この1回の実行で:
  (1) まだ記録していない「確定済み営業日」を全て遡って約定・記録（冪等・取りこぼし無し）
  (2) 「本日の発注プラン（目標ウェイト）」を表示
を行う。cron で毎営業日呼べば前向きにログが積み上がる。

用法:
  # 実データ(UM790等・要 yfinance + ネットワーク)
  python scripts/run_japan_equity_forward.py --source yfinance

  # 合成データ(動作確認)
  python scripts/run_japan_equity_forward.py --source synthetic
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from src.config import JP_LARGE_CAP, StrategyConfig
from src.data import load_japan_equity_data
from src.backtest import to_weights
from src.forward_test import DailyForwardSimulator
from src.signal import predict_next_day_jp_detailed


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", default="synthetic", choices=["synthetic", "yfinance"])
    p.add_argument("--state", default="state/japan_equity_forward.json")
    p.add_argument("--initial", type=float, default=1_000_000.0)
    p.add_argument("--start", default="2018-01-01")
    p.add_argument("--end", default=None)
    p.add_argument("--lam", type=float, default=0.9)
    p.add_argument("--factors", type=int, default=4)
    p.add_argument("--window", type=int, default=120)
    p.add_argument("--max-catchup", type=int, default=5,
                   help="1回の実行で遡って記録する確定日の最大数")
    args = p.parse_args()

    cfg = StrategyConfig(lam=args.lam, n_factors=args.factors, window=args.window)
    jp_tickers = list(JP_LARGE_CAP.keys())

    data_kwargs = {} if args.source == "synthetic" else {"start": args.start, "end": args.end}
    data = load_japan_equity_data(args.source, jp_tickers, **data_kwargs)

    us = data.us_cc.values
    jp = data.jp_oc.values
    dates = data.dates
    jp_cols = list(data.jp_oc.columns)
    T = len(dates)
    Wn = cfg.window

    print(f"[データ] {args.source}: 米国{data.n_us}業種 × 日本個別株{data.n_jp}銘柄 / "
          f"{T}営業日 ({dates[0].date()}〜{dates[-1].date()})")
    if T < Wn + 2:
        print(f"[エラー] データ不足 ({T} < {Wn + 2})。--window を小さくするか期間を延ばしてください。")
        sys.exit(1)

    sim = DailyForwardSimulator(args.state, initial_capital=args.initial)
    last = sim.last_date()

    def predict_and_weights(t: int):
        """決定日 t（us[t]=米国引け）から、t+1 の日本ウェイトを返す。"""
        pred, f_hat, _ = predict_next_day_jp_detailed(
            us[t - Wn:t], jp[t - Wn + 1:t + 1], us[t],
            lam=cfg.lam, k=cfg.n_factors)
        w = to_weights(pred, cfg)
        return w, float(np.linalg.norm(pred)), [float(x) for x in f_hat]

    # (1) 確定済みの未記録営業日を遡って約定・記録（冪等）
    #     決定日 t は Wn..T-2、約定/実現日は dates[t+1]。
    bookable = []
    for t in range(Wn, T - 1):
        exec_date = str(dates[t + 1].date())
        if last is not None and exec_date <= last:
            continue   # 既に記録済み → スキップ（冪等）
        bookable.append(t)

    bookable = bookable[-args.max_catchup:]  # 取りこぼし過大時は直近のみ
    if not bookable:
        print(f"[情報] 新たに確定した営業日はありません（最終記録: {last}）。")
    for t in bookable:
        w, sig, fsc = predict_and_weights(t)
        weights = {jp_cols[i]: float(w[i]) for i in range(len(jp_cols))}
        realized = {jp_cols[i]: float(jp[t + 1][i]) for i in range(len(jp_cols))}
        log = sim.step(dates[t + 1], weights, realized, cfg,
                       signal_strength=sig, factor_scores=fsc)
        print(f"[記録] {log.date}: net={log.net_return*100:+.3f}% "
              f"TO={log.turnover:.3f} signal={log.signal_strength:.4f} "
              f"→ ¥{log.equity:,.0f}")
    sim.save()

    # (2) 本日の発注プラン（最新の米国引け us[T-1] から、次の寄りで建てるウェイト）
    #     ※まだ実現していないので記録はしない（発注の参考）
    w_today, sig_today, _ = predict_and_weights(T - 1)
    order = sorted(
        ((jp_cols[i], float(w_today[i])) for i in range(len(jp_cols))),
        key=lambda x: -abs(x[1]))
    print(f"\n--- 本日の発注プラン（signal={sig_today:.4f}、次の寄りでリバランス） ---")
    shown = [o for o in order if abs(o[1]) > 1e-4][:12]
    for tk, w in shown:
        side = "LONG " if w > 0 else "SHORT"
        print(f"   {side} {tk:8s} {JP_LARGE_CAP.get(tk,''):10s}: {w:+.4f}")
    print(f"   (上位{len(shown)}銘柄を表示 / 全{data.n_jp}銘柄、グロス={np.abs(w_today).sum():.2f})")

    print()
    print(sim.report())


if __name__ == "__main__":
    main()
