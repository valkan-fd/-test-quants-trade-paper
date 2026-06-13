"""資金制約・手数料を考慮した寄り引けポジションのサイジングとコスト比較。

理想（等加重・コスト無）に対して、現実の制約でどれだけ目減りするかを比較する：
  - 単元(100株)＋一日信用 : 寄り/引けで両建て可。ただし 200万では数銘柄に集中。
  - 単元(100株)＋現物ロング : 空売り不可。買える銘柄だけ満額。
  - 端株(1株)＋現物ロング   : 多銘柄に分散できるが【空売り不可】かつ約定タイミング制約あり。

⚠️ 手数料は「既定の仮定値」。各社の最新料金で必ず上書きすること（FEES 参照）。
⚠️ 端株(単元未満株)は一般に【信用取引不可＝空売り不可】、約定タイミングも寄り等に限定され、
   「寄りで買い・引けで売る」寄り引けを正確には再現できない点に注意（long_only + 近似）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from . import config as C
from . import core


# ------------------------------------------------------------------ fee model
@dataclass
class FeeModel:
    name: str
    buy_rate: float = 0.0      # 買付手数料率（約定代金比）
    sell_rate: float = 0.0     # 売却手数料率
    min_fee: float = 0.0       # 1約定あたり最低手数料（円）
    fixed: float = 0.0         # 1約定あたり固定費（円）
    spread_bps: float = 0.0    # 片道スプレッド/実質コスト（bps）

    def leg_cost(self, notional: float, side: str) -> float:
        notional = abs(notional)
        rate = self.buy_rate if side == "buy" else self.sell_rate
        commission = 0.0
        if rate > 0 or self.min_fee > 0:
            commission = max(self.min_fee, rate * notional)
        commission += self.fixed
        spread = self.spread_bps / 1e4 * notional
        return commission + spread


# 既定の手数料プリセット（★要確認：各社の最新料金で上書き）
FEES = {
    "ideal":        FeeModel("ideal"),
    # 一日信用（大手は売買手数料0円が多い）。スリッページを片道3bps と仮置き。
    "ichinichi_margin": FeeModel("一日信用(単元)", spread_bps=3.0),
    # 単元・現物（通常手数料の例: 約定代金×0.05%、最低なし相当）+ スリッページ3bps
    "tan_genbutsu": FeeModel("単元現物", buy_rate=0.0005, sell_rate=0.0005, spread_bps=3.0),
    # 端株プリセット（現物ロングのみ） ----------------------------------------
    "sbi_skabu":    FeeModel("SBI S株", spread_bps=0.0),                 # 売買無料・基準値約定
    "monex_wankabu": FeeModel("マネックス ワン株", sell_rate=0.0055),    # 買無料/売0.55%
    "rakuten_kabumini": FeeModel("楽天 かぶミニ", spread_bps=22.0),       # リアルタイム片道0.22%
    "moomoo_hakabu": FeeModel("moomoo 端株(要確認)", spread_bps=0.0),    # ★実料金を要確認
}


# ------------------------------------------------------------------ scenario
@dataclass
class Scenario:
    name: str
    capital: float = C.CAPITAL
    lot: int = C.UNIT_SHARES        # 100=単元, 1=端株
    allow_short: bool = True
    fee_key: str = "ideal"
    alloc: str = "fill"             # "fill"=満額(貪欲) / "equal"=均等予算
    note: str = ""

    @property
    def fee(self) -> FeeModel:
        return FEES[self.fee_key]


def default_scenarios(capital: float = C.CAPITAL) -> list[Scenario]:
    return [
        Scenario("理想(等加重・コスト無)", capital, lot=1, allow_short=True, fee_key="ideal", alloc="equal"),
        Scenario("単元+一日信用(両建)", capital, lot=100, allow_short=True, fee_key="ichinichi_margin"),
        Scenario("単元+現物(ロングのみ)", capital, lot=100, allow_short=False, fee_key="tan_genbutsu"),
        Scenario("端株SBI(ロングのみ)", capital, lot=1, allow_short=False, fee_key="sbi_skabu"),
        Scenario("端株マネックス(ロングのみ)", capital, lot=1, allow_short=False, fee_key="monex_wankabu"),
        Scenario("端株楽天かぶミニ(ロングのみ)", capital, lot=1, allow_short=False, fee_key="rakuten_kabumini"),
        Scenario("端株moomoo(ロングのみ・要確認)", capital, lot=1, allow_short=False, fee_key="moomoo_hakabu"),
    ]


# ------------------------------------------------------------------ sizing
def _allocate_shares(prices: np.ndarray, tradable: np.ndarray, capital: float,
                     lot: int, alloc: str, n_universe: int) -> np.ndarray:
    """各銘柄の建て株数（>=0, lot 単位）を返す。価格は寄り(NextO)。

    - tradable: pos!=0 の銘柄マスク（売り禁/ロング不可で 0 にされた銘柄は False）
    - equal: 予算を【ユニバース全体 n_universe】で均等割り（建てない銘柄ぶんは現金）。理想時に等加重と一致。
    - fill : 建てられる銘柄に安い順で 1 ロットずつ貪欲に積み、満額に近づける。
    """
    n = len(prices)
    shares = np.zeros(n)
    if n == 0:
        return shares
    lot_cost = prices * lot
    if alloc == "equal":
        budget = capital / max(n_universe, 1)
        s = np.floor(budget / lot_cost) * lot
        return np.where(tradable, s, 0.0).astype(float)
    # fill: 建てられる銘柄だけを対象に安い順ラウンドロビン
    idx = [i for i in np.argsort(lot_cost) if tradable[i]]
    invested = 0.0
    progressed = True
    while progressed:
        progressed = False
        for i in idx:
            if invested + lot_cost[i] <= capital:
                shares[i] += lot
                invested += lot_cost[i]
                progressed = True
    return shares


def simulate(panel: pd.DataFrame, sc: Scenario, feature=None, direction=None, regime=None) -> pd.DataFrame:
    """シナリオの日次純リターンを返す（index=decision date）。"""
    feature = feature or C.SIGNAL_FEATURE
    direction = C.DIRECTION if direction is None else direction
    regime = regime or C.MARKET_REGIME

    base = panel[panel["InUniverse"]].dropna(subset=[feature, "Target", "NextO", "NextC"]).copy()
    base = core.filter_regime(base, regime)
    base["pos"] = core.compute_positions(base, feature, direction)
    if not sc.allow_short:
        base["pos"] = base["pos"].clip(lower=0.0)

    out = []
    for d, g in base.groupby(C.DATE_COL):
        o = g["NextO"].to_numpy(float)
        c = g["NextC"].to_numpy(float)
        sign = np.sign(g["pos"].to_numpy(float))
        n_universe = len(g)                       # その日のユニバース銘柄数（建てない銘柄も含む）
        shares = _allocate_shares(o, sign != 0, sc.capital, sc.lot, sc.alloc, n_universe)

        gross = float(np.sum(sign * shares * (c - o)))
        cost = 0.0
        for sh, oi, ci, sg in zip(shares, o, c, sign):
            if sh == 0:
                continue
            if sg > 0:    # ロング: 寄り買い→引け売り
                cost += sc.fee.leg_cost(sh * oi, "buy") + sc.fee.leg_cost(sh * ci, "sell")
            else:         # ショート: 寄り売り→引け買い
                cost += sc.fee.leg_cost(sh * oi, "sell") + sc.fee.leg_cost(sh * ci, "buy")
        deployed = float(np.sum(shares * o))
        out.append({C.DATE_COL: d,
                    "gross_ret": gross / sc.capital,
                    "fee_ret": cost / sc.capital,
                    "net_ret": (gross - cost) / sc.capital,
                    "n_held": int(np.sum(shares > 0)),
                    "deployed_ratio": deployed / sc.capital})
    res = pd.DataFrame(out).set_index(C.DATE_COL).sort_index()
    return res


# ------------------------------------------------------------------ compare
def _metrics(net: pd.Series, periods=252) -> dict:
    net = net.dropna()
    if net.empty:
        return dict(ann_return=np.nan, sharpe=np.nan, total_return=np.nan)
    mu, sd = net.mean(), net.std()
    eq = (1 + net).cumprod()
    return dict(
        ann_return=float((1 + mu) ** periods - 1),
        sharpe=float(mu / sd * np.sqrt(periods)) if sd > 0 else np.nan,
        total_return=float(eq.iloc[-1] - 1),
    )


def compare(panel: pd.DataFrame, scenarios=None, feature=None, direction=None, regime=None):
    """全シナリオを比較。(指標テーブル, エクイティDataFrame) を返す。

    目減りを2要因に分解して報告する：
      - sizing_drag : 単元丸め/銘柄数減/ショート不可 など【制約】による劣化（コスト無の gross 比較）
      - fee_drag    : 【手数料・スリッページ】そのものによる劣化（gross→net）
    """
    scenarios = scenarios or default_scenarios()
    rows, equity = [], {}
    ideal_gross_ann = None
    for sc in scenarios:
        sim = simulate(panel, sc, feature, direction, regime)
        gross = _metrics(sim["gross_ret"])
        net = _metrics(sim["net_ret"])
        if ideal_gross_ann is None:
            ideal_gross_ann = gross["ann_return"]
        equity[sc.name] = (1 + sim["net_ret"]).cumprod()
        rows.append({
            "scenario": sc.name,
            "net_ann(%)": round(100 * net["ann_return"], 2),
            "net_sharpe": round(net["sharpe"], 2) if net["sharpe"] == net["sharpe"] else np.nan,
            "net_total(%)": round(100 * net["total_return"], 1),
            "sizing_drag(%pt/yr)": round(100 * (ideal_gross_ann - gross["ann_return"]), 2),
            "fee_drag(%pt/yr)": round(100 * (gross["ann_return"] - net["ann_return"]), 2),
            "avg_n_held": round(float(sim["n_held"].mean()), 1),
            "avg_deployed(%)": round(100 * float(sim["deployed_ratio"].mean()), 1),
            "trade_days": int(len(sim)),
        })
    table = pd.DataFrame(rows)
    eq_df = pd.DataFrame(equity)
    return table, eq_df


def plot_equity(eq_df: pd.DataFrame, path: str):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    core.setup_japanese_font()
    fig, ax = plt.subplots(figsize=(13, 6))
    for col in eq_df.columns:
        ax.plot(eq_df.index, eq_df[col].values, lw=1.1, label=col)
    ax.axhline(1.0, color="gray", lw=0.8, ls="--")
    ax.set_title(f"資金{C.CAPITAL:,}円・寄り引け：制約/手数料シナリオ別 純資産（理想 vs 現実）")
    ax.set_xlabel("decision date"); ax.set_ylabel("net equity (start=1.0)")
    ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=110, bbox_inches="tight"); plt.close(fig)
