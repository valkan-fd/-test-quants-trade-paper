"""直近N年のバックテスト：指標算出・4特徴量バランスカーブ・採用シグナルのエクイティ。

フォワードテストの「期待値の基準」を作るのが目的。
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

from . import config as C
from . import core


# ------------------------------------------------------------------ metrics
def perf_metrics(daily: pd.Series, periods: int = 252) -> dict:
    """日次リターン series から各種指標を計算する。"""
    daily = daily.dropna().sort_index()
    if daily.empty:
        return dict(n_days=0, cumsum=np.nan, ann_return=np.nan, ann_vol=np.nan,
                    sharpe=np.nan, max_dd=np.nan, win_rate=np.nan)
    equity = (1.0 + daily).cumprod()
    dd = (equity / equity.cummax() - 1.0).min()
    mu, sd = daily.mean(), daily.std()
    return dict(
        n_days=int(daily.shape[0]),
        cumsum=float(daily.sum()),
        ann_return=float((1.0 + mu) ** periods - 1.0),
        ann_vol=float(sd * np.sqrt(periods)),
        sharpe=float(mu / sd * np.sqrt(periods)) if sd > 0 else np.nan,
        max_dd=float(dd),
        win_rate=float((daily > 0).mean()),
    )


def select_recent(panel: pd.DataFrame, years: int = C.ANALYSIS_YEARS) -> pd.DataFrame:
    """直近N年・ユニバース・ターゲット/市況が揃う行に絞る。"""
    last = panel[C.DATE_COL].max()
    start = last - pd.DateOffset(years=years)
    mask = (panel["InUniverse"] & (panel[C.DATE_COL] >= start)
            & panel["Target"].notna() & panel["SP500_cc"].notna())
    return panel.loc[mask].copy()


# --------------------------------------------------------------- run / report
def feature_regime_table(sub: pd.DataFrame, direction: int = C.DIRECTION) -> pd.DataFrame:
    """4特徴量 × 市況レジーム(上昇/下落) の指標表（ノートブックの図に対応）。"""
    rows = []
    for feat in C.FEATURES:
        for label, regime in [("US_up", "up"), ("US_down", "down")]:
            daily = core.daily_returns_for_feature(core.filter_regime(sub, regime), feat, direction)
            m = perf_metrics(daily)
            m.update(feature=feat, regime=label)
            rows.append(m)
    cols = ["feature", "regime", "n_days", "cumsum", "ann_return", "ann_vol", "sharpe", "max_dd", "win_rate"]
    return pd.DataFrame(rows)[cols]


def strategy_daily(sub: pd.DataFrame, feature=C.SIGNAL_FEATURE,
                   direction=C.DIRECTION, regime=C.MARKET_REGIME) -> pd.Series:
    """フォワードで実際に採用するシグナルの日次リターン（市況フィルタ適用）。"""
    return core.daily_returns_for_feature(core.filter_regime(sub, regime), feature, direction)


def run(panel: pd.DataFrame, outdir: str = C.RESULTS_DIR, make_plot: bool = True) -> dict:
    """バックテストを実行し CSV / 図を出力。指標 dict を返す。"""
    os.makedirs(outdir, exist_ok=True)
    sub = select_recent(panel)

    table = feature_regime_table(sub)
    table.to_csv(os.path.join(outdir, "oc_backtest_feature_metrics.csv"), index=False)

    strat = strategy_daily(sub)
    strat_metrics = perf_metrics(strat)
    pd.Series(strat_metrics).to_csv(os.path.join(outdir, "oc_backtest_strategy_metrics.csv"))

    if make_plot:
        _plot_feature_grid(sub, os.path.join(outdir, "oc_backtest_curves.png"))

    return {"feature_table": table, "strategy_metrics": strat_metrics,
            "n_dates": int(sub[C.DATE_COL].nunique())}


def _plot_feature_grid(sub: pd.DataFrame, path: str, direction: int = C.DIRECTION):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    core.setup_japanese_font()

    titles = {"OC": "OPEN-CLOSE騰落率 (C/O-1)", "ret1": "前日比 (AdjC pct_change 1)",
              "ret5": "直近5日騰落率 (pct_change 5)", "ret21": "直近21日騰落率 (pct_change 21)"}
    regimes = [("前日S&P500 上昇 (>0)", "up", "tab:red"),
               ("前日S&P500 下落 (<0)", "down", "tab:blue")]

    fig, axes = plt.subplots(2, 2, figsize=(16, 9))
    for ax, feat in zip(axes.ravel(), C.FEATURES):
        for label, regime, color in regimes:
            daily = core.daily_returns_for_feature(core.filter_regime(sub, regime), feat, direction)
            if daily.empty:
                continue
            curve = daily.cumsum()
            sr = perf_metrics(daily)["sharpe"]
            ax.plot(curve.index, curve.values, color=color, lw=1.0,
                    label=f"{label}  (日数={daily.shape[0]}, 累積={curve.iloc[-1]:+.3f}, SR={sr:.2f})")
        ax.axhline(0.0, color="gray", lw=0.8)
        ax.set_title(titles[feat]); ax.set_xlabel("Date"); ax.set_ylabel("累積リターン (cumsum)")
        ax.legend(fontsize=9, loc="upper left"); ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)
