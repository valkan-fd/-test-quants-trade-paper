"""日次フォワードテスト（ペーパー運用）。複数プロファイルを同時に検証できる。

既定で 2 つのプロファイルを並走させる：
  - A_short_margin : 単元(100株)＋一日信用（両建＝ショート可）。戦略フル。手数料は一日信用想定。
  - B_mini_long    : ミニ株/端株(1株)＋現物（ロング専用）。0円(moomoo/SBI想定)・多銘柄分散。

毎営業日 UM790 上で 1 回呼ぶ想定：
  1. 直近で寄り引けが確定した日について【手数料・資金制約込みのネットリターン】を計上しエクイティを伸ばす
  2. 翌営業日に執行予定の建玉（intended orders）を state に保存

各プロファイルは独立した state（state/oc_forward_<name>.json）に永続化するので、何度呼んでも二重計上しない。
データ取得（J-Quants）とは分離してあり、parquet が更新されていれば差分だけ前進する。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np
import pandas as pd

from . import config as C
from . import core
from . import sizing


# ------------------------------------------------------------------- profile
@dataclass
class Profile:
    name: str
    scenario: sizing.Scenario
    feature: str = C.SIGNAL_FEATURE
    regime: str = C.MARKET_REGIME
    direction: int = C.DIRECTION

    @property
    def state_path(self) -> str:
        return os.path.join(C.STATE_DIR, f"oc_forward_{self.name}.json")

    @property
    def returns_csv(self) -> str:
        return os.path.join(C.RESULTS_DIR, f"oc_forward_{self.name}.csv")

    @property
    def equity_png(self) -> str:
        return os.path.join(C.RESULTS_DIR, f"oc_forward_{self.name}.png")


def default_profiles(capital: float = C.CAPITAL) -> list[Profile]:
    return [
        Profile("A_short_margin",
                sizing.Scenario("単元+一日信用(両建)", capital, lot=100, allow_short=True,
                                fee_key="ichinichi_margin", alloc="fill"),
                feature=C.SIGNAL_FEATURE, regime=C.MARKET_REGIME),
        Profile("B_mini_long",
                sizing.Scenario("ミニ株(ロングのみ)", capital, lot=1, allow_short=False,
                                fee_key="moomoo_hakabu", alloc="fill"),
                feature=C.SIGNAL_FEATURE, regime=C.MARKET_REGIME),
    ]


# ------------------------------------------------------------------- state IO
def load_state(profile: Profile) -> dict:
    if os.path.exists(profile.state_path):
        with open(profile.state_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"profile": profile.name, "last_decision_date": None,
            "equity": float(profile.scenario.capital), "history": [], "pending": None,
            "scenario": {"capital": profile.scenario.capital, "lot": profile.scenario.lot,
                         "allow_short": profile.scenario.allow_short, "fee": profile.scenario.fee_key,
                         "feature": profile.feature, "regime": profile.regime}}


def save_state(state: dict, profile: Profile):
    os.makedirs(os.path.dirname(profile.state_path), exist_ok=True)
    with open(profile.state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, default=str)


# ---------------------------------------------------------------- pending
def pending_snapshot(panel: pd.DataFrame, profile: Profile) -> dict:
    """翌営業日に執行予定の建玉（Target 未確定の最新 decision date）。"""
    base = panel[panel["InUniverse"] & panel[profile.feature].notna()].copy()
    base = core.filter_regime(base, profile.regime)
    if base.empty:
        return {"decision_date": None, "positions": [], "note": "no universe"}
    no_target = base[base["Target"].isna()][C.DATE_COL]
    dd = no_target.max() if len(no_target) else base[C.DATE_COL].max()
    rows = base[base[C.DATE_COL] == dd].copy()
    rows["pos"] = core.compute_positions(rows, profile.feature, profile.direction)
    if not profile.scenario.allow_short:
        rows["pos"] = rows["pos"].clip(lower=0.0)
    rows = rows[rows["pos"] != 0.0]
    positions = [{"Code": str(r[C.CODE_COL]), "side": ("LONG" if r["pos"] > 0 else "SHORT"),
                  profile.feature: round(float(r[profile.feature]), 4)} for _, r in rows.iterrows()]
    return {"decision_date": str(pd.Timestamp(dd).date()),
            "n_long": sum(p["side"] == "LONG" for p in positions),
            "n_short": sum(p["side"] == "SHORT" for p in positions),
            "positions": positions}


# ---------------------------------------------------------------------- step
def step(profile: Profile, panel: pd.DataFrame = None, price=None, stock_list=None,
         alert=None, sp=None, state=None) -> dict:
    """1プロファイルを1ステップ前進させる。panel を渡せば再計算しない。"""
    if panel is None:
        if price is None:
            price, stock_list, alert = core.load_inputs()
        if sp is None:
            start = (price[C.DATE_COL].min() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
            end = (price[C.DATE_COL].max() + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
            sp = core.get_sp500_cc(start, end)
        panel = core.build_panel(price, stock_list, alert, sp)

    state = state or load_state(profile)

    # 手数料・資金制約込みの日次ネットリターン（決定日ごと）
    sim = sizing.simulate(panel, profile.scenario, profile.feature, profile.direction, profile.regime)

    last = state["last_decision_date"]
    last_ts = pd.Timestamp(last) if last else None
    dates = [d for d in sim.index if (last_ts is None or pd.Timestamp(d) > last_ts)]

    equity = float(state["equity"])
    new_rows = []
    for d in dates:
        row = sim.loc[d]
        equity *= (1.0 + float(row["net_ret"]))
        new_rows.append({"decision_date": str(pd.Timestamp(d).date()),
                         "net_ret": float(row["net_ret"]), "gross_ret": float(row["gross_ret"]),
                         "fee_ret": float(row["fee_ret"]), "n_held": int(row["n_held"]),
                         "equity": equity})

    state["history"].extend(new_rows)
    state["equity"] = equity
    if new_rows:
        state["last_decision_date"] = new_rows[-1]["decision_date"]
    state["pending"] = pending_snapshot(panel, profile)

    return {"profile": profile.name, "state": state, "new_days": len(new_rows),
            "equity": equity, "last_decision_date": state["last_decision_date"]}


# ------------------------------------------------------------------ run all
def run_all(write: bool = True, capital: float = C.CAPITAL, profiles=None) -> dict:
    """全プロファイルを1ステップ実行。state/CSV/図を出力し、比較図も描く。"""
    price, stock_list, alert = core.load_inputs()
    start = (price[C.DATE_COL].min() - pd.Timedelta(days=10)).strftime("%Y-%m-%d")
    end = (price[C.DATE_COL].max() + pd.Timedelta(days=2)).strftime("%Y-%m-%d")
    sp = core.get_sp500_cc(start, end)
    panel = core.build_panel(price, stock_list, alert, sp)

    profiles = profiles or default_profiles(capital)
    results, equity_curves = {}, {}
    for prof in profiles:
        res = step(prof, panel=panel, state=load_state(prof))
        state = res["state"]
        if write:
            save_state(state, prof)
            if state["history"]:
                hist = pd.DataFrame(state["history"])
                os.makedirs(C.RESULTS_DIR, exist_ok=True)
                hist.to_csv(prof.returns_csv, index=False)
                _plot_equity(hist, prof)
                d = hist.copy()
                d["decision_date"] = pd.to_datetime(d["decision_date"])
                equity_curves[prof.name] = d.set_index("decision_date")["equity"] / prof.scenario.capital
        results[prof.name] = res

    if write and equity_curves:
        _plot_compare(equity_curves)
    results["ran_at"] = datetime.now().isoformat(timespec="seconds")
    return results


# ------------------------------------------------------------------ plotting
def _plot_equity(hist: pd.DataFrame, profile: Profile):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    core.setup_japanese_font()
    d = hist.copy()
    d["decision_date"] = pd.to_datetime(d["decision_date"])
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(d["decision_date"], d["equity"], color="tab:green", lw=1.2)
    ax.axhline(profile.scenario.capital, color="gray", lw=0.8, ls="--")
    ax.set_title(f"フォワード(ペーパー) {profile.name}: {profile.scenario.name}")
    ax.set_xlabel("decision date"); ax.set_ylabel("equity (円)"); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(profile.equity_png, dpi=110, bbox_inches="tight"); plt.close(fig)


def _plot_compare(curves: dict, path: str = None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    core.setup_japanese_font()
    path = path or os.path.join(C.RESULTS_DIR, "oc_forward_compare.png")
    fig, ax = plt.subplots(figsize=(13, 6))
    for name, s in curves.items():
        ax.plot(s.index, s.values, lw=1.2, label=name)
    ax.axhline(1.0, color="gray", lw=0.8, ls="--")
    ax.set_title("フォワード(ペーパー)比較：A(ショート可) vs B(ミニ株long-only)　純資産(start=1.0)")
    ax.set_xlabel("decision date"); ax.set_ylabel("net equity (start=1.0)")
    ax.legend(fontsize=9, loc="upper left"); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=110, bbox_inches="tight"); plt.close(fig)
