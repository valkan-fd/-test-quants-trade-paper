"""寄り引け戦略ノートブック用の【合成サンプルデータ】生成スクリプト。

⚠️ ここで作るのは実データではなく、ノートブックを端から端まで動かして挙動を確認するための
   ダミーデータ。J-Quants の本物の価格・銘柄・売り禁データは各自で取得して差し替えること。

出力（data/jquantsapi/v2/ 配下）:
  - stock_prices_mod.parquet : Date, Code, O, H, L, C, V, AdjC, TurnoverValue
  - stock_list_mod.parquet   : Code, CompanyName, Mrgn
  - margin_alert.parquet     : Date, Code, RestrictedByJSF（売り禁発生/解除の疎なレコード）

使い方:
  python scripts/make_sample_data.py
"""
import os

import numpy as np
import pandas as pd

SEED = 42
N_CODES = 40
START = "2015-01-01"
END = "2026-06-12"

OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "jquantsapi", "v2")


def main():
    rng = np.random.default_rng(SEED)
    os.makedirs(OUT_DIR, exist_ok=True)

    # 営業日（平日）カレンダー
    dates = pd.bdate_range(START, END)
    codes = [f"{1300 + i * 7:04d}" for i in range(N_CODES)]  # 適当な4桁コード

    frames = []
    for ci, code in enumerate(codes):
        n = len(dates)
        # 弱い平均回帰（負の自己相関）を持つ日次リターン → 逆張りで弱い優位が出るように
        eps = rng.normal(0, 0.018, n)
        r = np.zeros(n)
        for t in range(1, n):
            r[t] = -0.06 * r[t - 1] + eps[t]
        close = 1000 * (1 + ci * 0.03) * np.exp(np.cumsum(r))

        prev_close = np.concatenate([[close[0]], close[:-1]])
        # 寄りは前日終値からの小さなギャップ
        open_ = prev_close * (1 + rng.normal(0, 0.006, n))
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))

        # 売買代金: 銘柄ごとの規模 × 日々のゆらぎ（TOP20 が日々入れ替わるように）
        scale = np.exp(rng.normal(0, 0.7))            # 銘柄規模
        vol = (rng.lognormal(13.0, 0.6, n) * scale).astype(np.int64)
        turnover = vol * close

        frames.append(pd.DataFrame({
            "Date": dates,
            "Code": code,
            "O": open_.round(1),
            "H": high.round(1),
            "L": low.round(1),
            "C": close.round(1),
            "V": vol,
            "AdjC": close.round(2),         # 分割なし想定（AdjC=C）
            "TurnoverValue": turnover.round(0),
        }))

    price = pd.concat(frames, ignore_index=True)
    price = price.sort_values(["Date", "Code"]).reset_index(drop=True)

    # --- 銘柄リスト（信用区分は静的） -----------------------------------------
    mrgn_choices = np.array(["貸借", "信用", "-"])
    stock_list = pd.DataFrame({
        "Code": codes,
        "CompanyName": [f"サンプル銘柄{c}" for c in codes],
        "Mrgn": rng.choice(mrgn_choices, size=len(codes), p=[0.55, 0.30, 0.15]),
    })

    # --- 日々公表（売り禁）: 一部銘柄に発生→解除の疎なレコード ------------------
    alert_rows = []
    restricted_codes = rng.choice(codes, size=10, replace=False)
    for code in restricted_codes:
        n_events = rng.integers(1, 4)
        starts = np.sort(rng.choice(len(dates) - 30, size=n_events, replace=False))
        for s in starts:
            dur = int(rng.integers(3, 25))
            alert_rows.append({"Date": dates[s], "Code": code, "RestrictedByJSF": "1"})       # 発生
            alert_rows.append({"Date": dates[s + dur], "Code": code, "RestrictedByJSF": "0"})  # 解除
    alert = (pd.DataFrame(alert_rows)
             .drop_duplicates(subset=["Date", "Code"])
             .sort_values(["Date", "Code"]).reset_index(drop=True))

    # --- 書き出し --------------------------------------------------------------
    price.to_parquet(os.path.join(OUT_DIR, "stock_prices_mod.parquet"), index=False)
    stock_list.to_parquet(os.path.join(OUT_DIR, "stock_list_mod.parquet"), index=False)
    alert.to_parquet(os.path.join(OUT_DIR, "margin_alert.parquet"), index=False)

    print("出力先:", OUT_DIR)
    print("stock_prices_mod:", price.shape, "| 期間:", price["Date"].min().date(), "〜", price["Date"].max().date())
    print("stock_list_mod  :", stock_list.shape)
    print("margin_alert    :", alert.shape)


if __name__ == "__main__":
    main()
