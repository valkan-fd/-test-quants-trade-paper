"""寄り引け戦略パッケージの軽量テスト。

合成のミニパネルで、リーク無し・売り禁マスク・フォワードの冪等性を確認する。
"""
import numpy as np
import pandas as pd

from oc_strategy import core, forward, sizing, backtest, config as C


def _mini_inputs(n_codes=25, n_days=80, seed=0):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    codes = [f"{1000+i:04d}" for i in range(n_codes)]
    frames = []
    for ci, code in enumerate(codes):
        r = rng.normal(0, 0.02, n_days)
        close = 1000 * np.exp(np.cumsum(r))
        prev = np.concatenate([[close[0]], close[:-1]])
        frames.append(pd.DataFrame({
            "Date": dates, "Code": code,
            "O": prev * (1 + rng.normal(0, 0.005, n_days)),
            "H": close * 1.01, "L": close * 0.99, "C": close,
            "V": rng.integers(1e5, 1e6, n_days),
            "AdjC": close,
            "TurnoverValue": close * rng.lognormal(13, 0.5, n_days),
        }))
    price = pd.concat(frames, ignore_index=True)
    stock_list = pd.DataFrame({"Code": codes, "Mrgn": "貸借"})
    alert = pd.DataFrame({"Date": [dates[10]], "Code": [codes[0]], "RestrictedByJSF": ["1"]})
    sp = pd.DataFrame({"Date": dates, "SP500_cc": rng.normal(0, 0.01, n_days)})
    return price, stock_list, alert, sp


def test_universe_size():
    price, sl, al, sp = _mini_inputs()
    panel = core.build_panel(price, sl, al, sp)
    per_day = panel.groupby("Date")["InUniverse"].sum()
    assert (per_day <= C.TOP_N).all()
    assert per_day.max() == C.TOP_N


def test_no_lookahead_target():
    """Target は当該行の翌日 O/C のみで決まり、未来の特徴量に依存しない。"""
    price, sl, al, sp = _mini_inputs()
    panel = core.build_panel(price, sl, al, sp).sort_values(["Code", "Date"])
    g = panel[panel["Code"] == panel["Code"].iloc[0]].reset_index(drop=True)
    # 各行の NextO/NextC が翌行の O/C と一致
    assert np.allclose(g["NextO"].iloc[:-1], g["O"].shift(-1).iloc[:-1])
    assert np.allclose(g["NextC"].iloc[:-1], g["C"].shift(-1).iloc[:-1])


def test_short_restriction_flattens_short():
    """売り禁の銘柄はショート方向だとフラット(0)になる。"""
    df = pd.DataFrame({
        "ret5": [-0.1, -0.1],            # 逆張りなら +sign? いや direction=-1 → pos = -sign(-0.1)= +1 (long)
        "Target": [0.0, 0.0],
        "RestrictedByJSF": ["1", "0"],
    })
    # ショートを作るため direction=+1（pos=sign(-0.1)=-1 = short）にして規制行が0になることを見る
    pos = core.compute_positions(df, "ret5", direction=1)
    assert pos.iloc[0] == 0.0    # 規制ありショート → フラット
    assert pos.iloc[1] == -1.0   # 規制なしショート → そのまま


def test_ideal_sizing_matches_equal_weight():
    """理想シナリオ(端株・コスト無・均等予算)の日次純リターンは等加重 mean(pos*Target) に一致。"""
    price, sl, al, sp = _mini_inputs()
    panel = core.build_panel(price, sl, al, sp)
    sc = sizing.Scenario("ideal", capital=1e12, lot=1, allow_short=True, fee_key="ideal", alloc="equal")
    sim = sizing.simulate(panel, sc, feature="ret5")
    ref = core.daily_returns_for_feature(panel[panel["InUniverse"]], "ret5")
    common = sim.index.intersection(ref.index)
    assert len(common) > 0
    assert np.allclose(sim.loc[common, "net_ret"], ref.loc[common], atol=1e-6)


def test_unit_lot_drops_unaffordable():
    """単元・少額資金では値がさ株を持てない（買える銘柄数が減る）。"""
    price, sl, al, sp = _mini_inputs()
    panel = core.build_panel(price, sl, al, sp)
    big = sizing.Scenario("big", capital=1e9, lot=100, allow_short=True, fee_key="ideal", alloc="equal")
    small = sizing.Scenario("small", capital=300_000, lot=100, allow_short=True, fee_key="ideal", alloc="equal")
    n_big = sizing.simulate(panel, big, feature="ret5")["n_held"].mean()
    n_small = sizing.simulate(panel, small, feature="ret5")["n_held"].mean()
    assert n_small < n_big


def test_percent_fee_creates_drag():
    """%課金は純リターンを必ず押し下げる（fee_drag > 0）。"""
    price, sl, al, sp = _mini_inputs()
    panel = core.build_panel(price, sl, al, sp)
    sc = sizing.Scenario("monex", capital=2_000_000, lot=1, allow_short=False,
                         fee_key="monex_wankabu", alloc="fill")
    sim = sizing.simulate(panel, sc, feature="ret5")
    assert (sim["fee_ret"] >= 0).all()
    assert sim["fee_ret"].sum() > 0


def test_side_decomposition_partitions():
    """long/short の side は両建のポジションを符号で分けたもの。長短の日数は両建以下。"""
    price, sl, al, sp = _mini_inputs()
    panel = core.build_panel(price, sl, al, sp)
    sub = panel[panel["InUniverse"]].dropna(subset=["ret5", "Target"])
    both = core.daily_returns_for_feature(sub, "ret5", side="both")
    lo = core.daily_returns_for_feature(sub, "ret5", side="long")
    sh = core.daily_returns_for_feature(sub, "ret5", side="short")
    assert len(lo) <= len(both) and len(sh) <= len(both)
    # 端株long-only専用の指標が計算できる
    tbl = backtest.side_decomposition(sub)
    assert set(tbl["side"]) == {"both", "long", "short"}
    assert tbl["sharpe"].notna().any()


def test_forward_idempotent_and_no_double_count():
    price, sl, al, sp = _mini_inputs()
    panel = core.build_panel(price, sl, al, sp)
    prof = forward.default_profiles(capital=2_000_000)[1]   # B_mini_long
    state = forward.load_state(prof)
    r1 = forward.step(prof, panel=panel, state=state)
    assert r1["new_days"] > 0
    r2 = forward.step(prof, panel=panel, state=r1["state"])
    assert r2["new_days"] == 0          # 同じデータなら追加なし
    hist = pd.DataFrame(r2["state"]["history"])
    assert len(hist) == hist["decision_date"].nunique()   # 二重計上なし


def test_forward_two_profiles_independent():
    """A(ショート可) と B(ロング専用) は別 state で独立に積み上がる。"""
    price, sl, al, sp = _mini_inputs()
    panel = core.build_panel(price, sl, al, sp)
    profs = forward.default_profiles(capital=2_000_000)
    a = forward.step(profs[0], panel=panel, state=forward.load_state(profs[0]))
    b = forward.step(profs[1], panel=panel, state=forward.load_state(profs[1]))
    assert a["profile"] == "A_short_margin" and b["profile"] == "B_mini_long"
    # B はロング専用なので pending にショートは無い
    bp = b["state"]["pending"]
    assert bp.get("n_short", 0) == 0
