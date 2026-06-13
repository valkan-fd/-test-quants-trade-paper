"""日次フォワードテスト（ペーパー運用）。

毎営業日 UM790 上で 1 回呼ぶ想定：
  1. 最新データから（前日終値時点の）翌日ポジションを決定し state に保存（=未実現の建玉）
  2. 直近で寄り引けが確定した日について実現リターンを計上し、エクイティ曲線を伸ばす

state（state/oc_forward_state.json）に進捗を永続化するので、何度呼んでも二重計上しない。
データ取得（J-Quants）とは分離してあり、parquet が更新されていれば差分だけ前進する。
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

from . import config as C
from . import core


# ------------------------------------------------------------------- state IO
def load_state(path: str = C.FORWARD_STATE_PATH) -> dict:
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"last_decision_date": None, "equity": float(C.INITIAL_EQUITY),
            "history": [], "pending": None,
            "config": {"feature": C.SIGNAL_FEATURE, "direction": C.DIRECTION,
                       "regime": C.MARKET_REGIME, "top_n": C.TOP_N}}


def save_state(state: dict, path: str = C.FORWARD_STATE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, default=str)


# ----------------------------------------------------------------- decisions
def _date_return(sub_date: pd.DataFrame, feature: str, direction: int) -> float:
    """1日分のユニバース行から等加重の実現リターンを計算（市況フィルタ後の行を渡す）。"""
    d = sub_date.dropna(subset=[feature, "Target"])
    if d.empty:
        return 0.0
    pos = core.compute_positions(d, feature, direction)
    return float((pos * d["Target"]).mean())


def decision_snapshot(panel: pd.DataFrame, date, feature, direction, regime) -> dict:
    """指定 decision date のユニバースに対する建玉スナップショット（翌営業日に執行予定）。"""
    rows = panel[(panel[C.DATE_COL] == date) & panel["InUniverse"] & panel[feature].notna()].copy()
    rows = core.filter_regime(rows, regime)
    if rows.empty:
        return {"decision_date": str(pd.Timestamp(date).date()), "positions": [], "note": "no position (regime filtered or empty)"}
    rows["pos"] = core.compute_positions(rows, feature, direction)
    positions = [{"Code": str(r[C.CODE_COL]), "pos": float(r["pos"]),
                  feature: float(r[feature]),
                  "RestrictedByJSF": (None if pd.isna(r["RestrictedByJSF"]) else str(r["RestrictedByJSF"]))}
                 for _, r in rows.iterrows()]
    n_long = sum(1 for p in positions if p["pos"] > 0)
    n_short = sum(1 for p in positions if p["pos"] < 0)
    n_flat = sum(1 for p in positions if p["pos"] == 0)
    return {"decision_date": str(pd.Timestamp(date).date()),
            "n_universe": len(positions), "n_long": n_long, "n_short": n_short, "n_flat": n_flat,
            "positions": positions}


# ---------------------------------------------------------------------- step
def step(price=None, stock_list=None, alert=None, sp=None, state=None,
         feature=None, direction=None, regime=None) -> dict:
    """フォワードテストを1ステップ前進させる。

    sp（S&P500 CLOSE-CLOSE）を渡さなければ yfinance で取得する（要ネットワーク）。
    テスト時は price/stock_list/alert/sp を直接注入できる。
    """
    if price is None:
        price, stock_list, alert = core.load_inputs()
    feature = feature or C.SIGNAL_FEATURE
    direction = C.DIRECTION if direction is None else direction
    regime = regime or C.MARKET_REGIME

    if sp is None:
        start = (price[C.DATE_COL].min() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
        end = (price[C.DATE_COL].max() + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
        sp = core.get_sp500_cc(start, end)

    panel = core.build_panel(price, stock_list, alert, sp)
    state = state or load_state()

    last = state["last_decision_date"]
    last_ts = pd.Timestamp(last) if last else None

    # 実現対象: Target が確定した decision date のうち未計上のもの（市況が揃う日）
    realizable = panel[panel["Target"].notna() & panel["InUniverse"] & panel["SP500_cc"].notna()]
    dates = np.sort(realizable[C.DATE_COL].unique())
    if last_ts is not None:
        dates = [d for d in dates if pd.Timestamp(d) > last_ts]

    new_rows = []
    equity = float(state["equity"])
    for d in dates:
        sub = core.filter_regime(realizable[realizable[C.DATE_COL] == d], regime)
        ret = _date_return(sub, feature, direction)
        equity *= (1.0 + ret)
        new_rows.append({"decision_date": str(pd.Timestamp(d).date()), "ret": ret, "equity": equity})

    state["history"].extend(new_rows)
    state["equity"] = equity
    if new_rows:
        state["last_decision_date"] = new_rows[-1]["decision_date"]

    # 翌営業日に執行予定の建玉（Target 未確定の最新日 = 直近の完了日）
    pend_dates = panel[panel["InUniverse"] & panel[feature].notna()][C.DATE_COL]
    if len(pend_dates):
        latest = pend_dates.max()
        # Target が無い（=まだ翌日が来ていない）最新の decision date を採用
        no_target = panel[(panel["InUniverse"]) & (panel[feature].notna()) & (panel["Target"].isna())][C.DATE_COL]
        decision_date = no_target.max() if len(no_target) else latest
        state["pending"] = decision_snapshot(panel, decision_date, feature, direction, regime)

    return {"state": state, "new_days": len(new_rows), "equity": equity,
            "last_decision_date": state["last_decision_date"]}


def run_once(write: bool = True) -> dict:
    """CLI 用：1ステップ実行し、state と履歴 CSV を書き出す。"""
    res = step()
    state = res["state"]
    if write:
        save_state(state)
        if state["history"]:
            hist = pd.DataFrame(state["history"])
            os.makedirs(C.RESULTS_DIR, exist_ok=True)
            hist.to_csv(C.FORWARD_RETURNS_PATH, index=False)
            _plot_equity(hist)
    res["ran_at"] = datetime.now().isoformat(timespec="seconds")
    return res


def _plot_equity(hist: pd.DataFrame, path: str = C.FORWARD_EQUITY_PNG):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    try:
        import japanize_matplotlib  # noqa: F401
    except Exception:
        pass
    d = hist.copy()
    d["decision_date"] = pd.to_datetime(d["decision_date"])
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(d["decision_date"], d["equity"], color="tab:green", lw=1.2)
    ax.axhline(C.INITIAL_EQUITY, color="gray", lw=0.8, ls="--")
    ax.set_title("寄り引け戦略 フォワードテスト（ペーパー）エクイティ")
    ax.set_xlabel("decision date"); ax.set_ylabel("equity"); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=110, bbox_inches="tight"); plt.close(fig)
