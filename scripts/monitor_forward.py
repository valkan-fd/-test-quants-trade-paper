#!/usr/bin/env python3
"""フォワード運用ダッシュボード — state JSON から運用成績を監視.

日次で `run_japan_equity_forward.py` が記録した JSON を読み込み、
累積P&L、期間別Sharpe、ドローダウン等をリアルタイム表示。

用法:
  python scripts/monitor_forward.py --state state/japan_equity_forward.json

出力: CSV 形式で標準出力 → ファイルリダイレクト or スプレッドシート化可能。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd


def load_state(path: str | Path) -> dict:
    """JSON 状態ファイルを読み込む."""
    with open(path) as f:
        return json.load(f)


def compute_cumulative_metrics(logs: list[dict], initial_capital: float | None = None) -> dict:
    """ログから累積指標を計算.

    total_return は initial_capital を基準にする（初日の損益も含める）。
    """
    if not logs:
        return {}

    rets = pd.Series([log['net_return'] for log in logs])
    equity = pd.Series([log['equity'] for log in logs])
    dates = pd.Series([pd.to_datetime(log['date']) for log in logs])

    n_days = len(rets)
    base = initial_capital if initial_capital else equity.iloc[0]
    total_ret = equity.iloc[-1] / base - 1 if len(equity) > 0 else 0
    annual_ret = total_ret * 252 / max(n_days, 1)

    # ボラティリティ（年率）
    vol = rets.std(ddof=1) if len(rets) > 1 else 0
    annual_vol = vol * np.sqrt(252)

    # Sharpe
    sharpe = (rets.mean() / vol * np.sqrt(252)) if vol > 1e-12 else float('nan')

    # 最大ドローダウン
    cum_equity = (1 + rets).cumprod()
    dd = (cum_equity / cum_equity.cummax() - 1).min() if len(cum_equity) > 0 else 0

    # 勝率
    hit_rate = (rets > 0).mean()

    # 期間
    duration = dates.iloc[-1] - dates.iloc[0] if len(dates) > 1 else timedelta(0)

    return {
        'n_days': n_days,
        'total_return': float(total_ret),
        'annual_return': float(annual_ret),
        'annual_vol': float(annual_vol),
        'sharpe': float(sharpe),
        'max_drawdown': float(dd),
        'hit_rate': float(hit_rate),
        'duration_days': int(duration.days),
    }


def rolling_monthly_performance(logs: list[dict], window_days: int = 21) -> pd.DataFrame:
    """ローリング月間（営業日ベース）のパフォーマンス."""
    if not logs:
        return pd.DataFrame()

    df = pd.DataFrame(logs)
    df['date'] = pd.to_datetime(df['date'])
    df = df.set_index('date').sort_index()

    monthly_rets = []
    for i in range(0, len(df), window_days):
        window_df = df.iloc[i:i+window_days]
        if len(window_df) == 0:
            continue
        period_ret = (1 + window_df['net_return']).prod() - 1
        start_date = window_df.index[0]
        end_date = window_df.index[-1]
        n_trades = len(window_df)

        monthly_rets.append({
            'start_date': start_date.date(),
            'end_date': end_date.date(),
            'period_return': float(period_ret),
            'n_trades': n_trades,
        })

    return pd.DataFrame(monthly_rets)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--state", default="state/japan_equity_forward.json")
    p.add_argument("--format", default="table", choices=["table", "csv", "json"])
    p.add_argument("--window", type=int, default=21, help="ローリング期間(営業日)")
    args = p.parse_args()

    state_path = Path(args.state)
    if not state_path.exists():
        print(f"[エラー] {state_path} が見つかりません", file=sys.stderr)
        sys.exit(1)

    state = load_state(state_path)
    logs = state.get('logs', [])
    current_equity = state.get('current_equity', state.get('initial_capital', 0))
    initial_capital = state.get('initial_capital', 0)

    metrics = compute_cumulative_metrics(logs, initial_capital=initial_capital)
    monthly = rolling_monthly_performance(logs, window_days=args.window)

    if args.format == "table":
        print("=" * 70)
        print(f"フォワード運用ダッシュボード — {state_path.name}")
        print("=" * 70)
        print(f"初期資金          : ¥{initial_capital:,.0f}")
        print(f"現在評価額        : ¥{current_equity:,.0f}")
        print(f"累積リターン      : {metrics.get('total_return', 0)*100:+.2f}%")
        print()
        print(f"運用日数          : {metrics.get('n_days', 0)} 日")
        print(f"期間              : {metrics.get('duration_days', 0)} 日")
        print(f"年率リターン(参考): {metrics.get('annual_return', 0)*100:+.2f}%")
        print(f"年率ボラティリティ: {metrics.get('annual_vol', 0)*100:.2f}%")
        print(f"Sharpe Ratio      : {metrics.get('sharpe', float('nan')):.2f}")
        print(f"最大ドローダウン  : {metrics.get('max_drawdown', 0)*100:.2f}%")
        print(f"勝率（日次）      : {metrics.get('hit_rate', 0)*100:.2f}%")
        print()

        if len(logs) > 0:
            print("直近5営業日:")
            for log in logs[-5:]:
                print(f"  {log['date']}: {log['net_return']*100:+.3f}% "
                      f"(equity: ¥{log['equity']:,.0f}) "
                      f"signal={log['signal_strength']:.4f} "
                      f"TO={log['turnover']:.3f}")
        print()

        if len(monthly) > 0:
            print(f"月次パフォーマンス (ローリング {args.window}営業日):")
            for _, row in monthly.tail(6).iterrows():
                print(f"  {row['start_date']} - {row['end_date']}: "
                      f"{row['period_return']*100:+.2f}% ({row['n_trades']} trades)")

    elif args.format == "csv":
        # ログを CSV 出力
        if logs:
            log_df = pd.DataFrame(logs)
            print(log_df[['date', 'net_return', 'turnover', 'equity']].to_csv(index=False))

    elif args.format == "json":
        out = {
            'metrics': metrics,
            'monthly': monthly.to_dict('records'),
            'state': {k: v for k, v in state.items() if k != 'logs'},
        }
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
