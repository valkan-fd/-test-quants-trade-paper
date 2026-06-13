"""寄り引け戦略パッケージの軽量テスト。

合成のミニパネルで、リーク無し・売り禁マスク・フォワードの冪等性を確認する。
"""
import numpy as np
import pandas as pd

from oc_strategy import core, forward, config as C


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


def test_forward_idempotent_and_no_double_count():
    price, sl, al, sp = _mini_inputs()
    state = {"last_decision_date": None, "equity": float(C.INITIAL_EQUITY),
             "history": [], "pending": None, "config": {}}
    r1 = forward.step(price=price, stock_list=sl, alert=al, sp=sp, state=state)
    n1 = r1["new_days"]
    assert n1 > 0
    r2 = forward.step(price=price, stock_list=sl, alert=al, sp=sp, state=r1["state"])
    assert r2["new_days"] == 0          # 同じデータなら追加なし
    hist = pd.DataFrame(r2["state"]["history"])
    assert len(hist) == hist["decision_date"].nunique()   # 二重計上なし
