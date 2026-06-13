"""ロング・ショート・バックテスター + 評価指標.

毎営業日 t について:
  - 過去窓の (米国当日, 日本翌日) ペアで部分空間正則化PCAを学習
  - 予測日 t の米国リターンから日本翌日リターン r̂_jp(t+1) を予測
  - 横断デマーン(マーケットニュートラル)してロング・ショートのウェイトに変換
  - 実現 jp_oc[t+1] でリターンを計上、ターンオーバーに取引コストを課す

リーク防止: 決定日 t で使うのは us_cc[t] と、窓内の (us_cc[i], jp_oc[i+1])
(i <= t-1) のみ。これらはすべて日本市場 t+1 の寄り付き前に観測可能。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .data import MarketData
from .signal import predict_next_day_jp


def to_weights(pred: np.ndarray, cfg: StrategyConfig) -> np.ndarray:
    """予測リターンをポートフォリオウェイトに変換。"""
    w = pred.astype(float).copy()
    if cfg.market_neutral:
        w = w - w.mean()             # 横断デマーン(ドルニュートラル)

    if cfg.top_k_positions:          # 上位/下位 k だけ残す
        k = cfg.top_k_positions
        idx = np.argsort(w)
        mask = np.zeros_like(w, dtype=bool)
        mask[idx[:k]] = True         # 下位k(ショート)
        mask[idx[-k:]] = True        # 上位k(ロング)
        w[~mask] = 0.0

    if not cfg.long_short:
        w = np.clip(w, 0, None)      # ロングオンリー

    gross = np.abs(w).sum()
    if gross > 1e-12:
        w = w / gross * cfg.gross_exposure
    return w


@dataclass
class BacktestResult:
    daily_returns: pd.Series       # 戦略の日次リターン
    weights: pd.DataFrame          # 日次ウェイト(index=実現日 t+1)
    turnover: pd.Series
    equity_curve: pd.Series
    metrics: dict

    def summary(self) -> str:
        m = self.metrics
        return (
            f"  年率リターン      : {m['annual_return']*100:6.2f} %\n"
            f"  年率ボラティリティ: {m['annual_vol']*100:6.2f} %\n"
            f"  リスクリワード R/R: {m['sharpe']:6.2f}\n"
            f"  最大ドローダウン  : {m['max_drawdown']*100:6.2f} %\n"
            f"  勝率(日次)        : {m['hit_rate']*100:6.2f} %\n"
            f"  平均ターンオーバー: {m['avg_turnover']:6.3f}\n"
            f"  日数              : {m['n_days']}\n"
        )


def compute_metrics(rets: pd.Series, turnover: pd.Series,
                    cfg: StrategyConfig) -> dict:
    ann = cfg.trading_days
    mu = rets.mean() * ann
    vol = rets.std(ddof=1) * np.sqrt(ann)
    sharpe = mu / vol if vol > 1e-12 else float("nan")
    eq = (1 + rets).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    return {
        "annual_return": float(mu),
        "annual_vol": float(vol),
        "sharpe": float(sharpe),
        "max_drawdown": float(dd),
        "hit_rate": float((rets > 0).mean()),
        "avg_turnover": float(turnover.mean()),
        "n_days": int(len(rets)),
        "total_return": float(eq.iloc[-1] - 1) if len(eq) else 0.0,
    }


def run_backtest(data: MarketData, cfg: StrategyConfig,
                 variant: str = "shrink") -> BacktestResult:
    us = data.us_cc.values
    jp = data.jp_oc.values
    dates = data.dates
    T = len(dates)
    W = cfg.window

    rec_dates, rec_rets, rec_to = [], [], []
    rec_w = []
    prev_w = np.zeros(data.n_jp)

    # 決定日 t: 窓 [t-W, t-1] のペア(us[i], jp[i+1]) を学習し、us[t]->jp[t+1] を予測。
    # よって t は W..T-2 を走る(t+1 が存在する範囲)。
    for t in range(W, T - 1):
        us_window = us[t - W:t]            # (W, n_us)  i = t-W .. t-1
        jp_window_next = jp[t - W + 1:t + 1]  # (W, n_jp) i+1 = t-W+1 .. t
        us_today = us[t]                   # 予測日の米国リターン

        pred = predict_next_day_jp(
            us_window, jp_window_next, us_today,
            lam=cfg.lam, k=cfg.n_factors, variant=variant,
        )
        w = to_weights(pred, cfg)

        realized = jp[t + 1]               # 実現する日本翌日リターン
        gross_ret = float(np.dot(w, realized))
        turn = float(np.abs(w - prev_w).sum())
        cost = turn * cfg.cost_bps / 1e4
        net_ret = gross_ret - cost

        rec_dates.append(dates[t + 1])
        rec_rets.append(net_ret)
        rec_to.append(turn)
        rec_w.append(w)
        prev_w = w

    rets = pd.Series(rec_rets, index=pd.DatetimeIndex(rec_dates), name="strategy")
    turnover = pd.Series(rec_to, index=rets.index, name="turnover")
    weights = pd.DataFrame(rec_w, index=rets.index, columns=data.jp_oc.columns)
    equity = (1 + rets).cumprod()
    metrics = compute_metrics(rets, turnover, cfg)
    return BacktestResult(rets, weights, turnover, equity, metrics)


def run_momentum_baseline(data: MarketData, cfg: StrategyConfig,
                          lookback: int = 20) -> BacktestResult:
    """ベースライン: 日本セクターの単純モメンタム(過去lookback日)ロング・ショート。"""
    jp = data.jp_oc
    dates = data.dates
    rec_dates, rec_rets, rec_to, rec_w = [], [], [], []
    prev_w = np.zeros(data.n_jp)
    vals = jp.values
    for t in range(lookback, len(dates) - 1):
        mom = vals[t - lookback:t].sum(axis=0)
        w = to_weights(mom, cfg)
        realized = vals[t + 1]
        turn = float(np.abs(w - prev_w).sum())
        net = float(np.dot(w, realized)) - turn * cfg.cost_bps / 1e4
        rec_dates.append(dates[t + 1]); rec_rets.append(net)
        rec_to.append(turn); rec_w.append(w); prev_w = w
    rets = pd.Series(rec_rets, index=pd.DatetimeIndex(rec_dates), name="momentum")
    turnover = pd.Series(rec_to, index=rets.index)
    weights = pd.DataFrame(rec_w, index=rets.index, columns=jp.columns)
    equity = (1 + rets).cumprod()
    return BacktestResult(rets, weights, turnover, equity,
                          compute_metrics(rets, turnover, cfg))
