"""寄り引け戦略の中核ロジック（バックテスト・フォワードで共有）。

ノートブック notebooks/oc_strategy_analysis.ipynb と同じ計算をモジュール化したもの。
- データ読み込み / Date 正規化
- 売買代金 TOP20 ユニバース
- 信用区分(Mrgn)・売り禁(RestrictedByJSF) のマージ + ffill
- 特徴量 / ターゲット
- S&P500 前日 CLOSE-CLOSE 騰落率のマージ
- 符号売買の日次リターン
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import config as C


# ----------------------------------------------------------------- plotting
def setup_japanese_font():
    """matplotlib の日本語フォントを設定（japanize 優先、無ければ既存CJKフォント探索）。"""
    import matplotlib.pyplot as plt
    try:
        import japanize_matplotlib  # noqa: F401
        return
    except Exception:
        pass
    from matplotlib import font_manager
    for name in ["IPAexGothic", "IPAPGothic", "Noto Sans CJK JP", "Noto Sans CJK JP Regular",
                 "Hiragino Sans", "Yu Gothic", "Meiryo", "TakaoPGothic", "MS Gothic"]:
        if any(name in f.name for f in font_manager.fontManager.ttflist):
            plt.rcParams["font.family"] = name
            break
    plt.rcParams["axes.unicode_minus"] = False


# --------------------------------------------------------------------------- IO
def normalize_date(df: pd.DataFrame, col: str = C.DATE_COL) -> pd.DataFrame:
    """Date 列を tz なし datetime64[ns] に正規化する。"""
    s = pd.to_datetime(df[col])
    try:
        s = s.dt.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    df[col] = s.dt.normalize()
    return df


def load_inputs(price_path=C.PRICE_PATH, list_path=C.LIST_PATH, alert_path=C.ALERT_PATH):
    """price / stock_list / alert の 3 parquet を読み込む。"""
    price = normalize_date(pd.read_parquet(price_path))
    stock_list = pd.read_parquet(list_path)
    alert = pd.read_parquet(alert_path)
    return price, stock_list, alert


# ------------------------------------------------------------------- universe
def detect_turnover(df: pd.DataFrame) -> pd.Series:
    """売買代金列を検出。無ければ 終値×出来高 で近似する。"""
    for c in ["TurnoverValue", "Turnover", "TradingValue", "DealValue", "Value", "TV", "Amount"]:
        if c in df.columns:
            return df[c].astype(float)
    close_col = "C" if "C" in df.columns else ("Close" if "Close" in df.columns else None)
    vol_col = next((v for v in ["V", "Volume", "Vol", "AdjV", "AdjVolume"] if v in df.columns), None)
    if close_col and vol_col:
        return df[close_col].astype(float) * df[vol_col].astype(float)
    raise KeyError("売買代金を構成できる列が見つかりません: " + str(list(df.columns)))


# --------------------------------------------------------------------- merges
def merge_margin(df: pd.DataFrame, stock_list: pd.DataFrame) -> pd.DataFrame:
    """信用区分 Mrgn をマージして銘柄ごとに ffill。"""
    if "Mrgn" not in stock_list.columns:
        raise KeyError("stock_list に Mrgn 列がありません: " + str(list(stock_list.columns)))
    if C.DATE_COL in stock_list.columns:
        sl = normalize_date(stock_list.copy())[[C.DATE_COL, C.CODE_COL, "Mrgn"]].drop_duplicates()
        df = df.merge(sl, on=[C.DATE_COL, C.CODE_COL], how="left")
    else:
        sl = stock_list[[C.CODE_COL, "Mrgn"]].drop_duplicates(subset=[C.CODE_COL])
        df = df.merge(sl, on=C.CODE_COL, how="left")
    df = df.sort_values([C.CODE_COL, C.DATE_COL]).reset_index(drop=True)
    df["Mrgn"] = df.groupby(C.CODE_COL)["Mrgn"].ffill()
    return df


def merge_short_restriction(df: pd.DataFrame, alert: pd.DataFrame) -> pd.DataFrame:
    """売り禁 RestrictedByJSF をマージして銘柄ごとに ffill（発生日以降を継続）。"""
    if "RestrictedByJSF" not in alert.columns:
        raise KeyError("alert に RestrictedByJSF 列がありません: " + str(list(alert.columns)))
    al = normalize_date(alert.copy())[[C.DATE_COL, C.CODE_COL, "RestrictedByJSF"]]
    al = al.drop_duplicates(subset=[C.DATE_COL, C.CODE_COL])
    df = df.merge(al, on=[C.DATE_COL, C.CODE_COL], how="left")
    df = df.sort_values([C.CODE_COL, C.DATE_COL]).reset_index(drop=True)
    df["RestrictedByJSF"] = df.groupby(C.CODE_COL)["RestrictedByJSF"].ffill()
    return df


def is_short_restricted(series: pd.Series) -> pd.Series:
    """売り禁フラグを bool 化（0/'0'/False/空/NaN を規制なし、それ以外を規制ありとみなす）。"""
    def _f(v):
        if pd.isna(v):
            return False
        return str(v).strip() not in ("", "0", "0.0", "False", "false", "FALSE", "nan", "NaN", "None")
    return series.map(_f)


# ------------------------------------------------------------------- features
def add_features(df: pd.DataFrame) -> pd.DataFrame:
    """OC / ret1 / ret5 / ret21 を付与（Code ごと・Date 昇順前提）。"""
    df = df.sort_values([C.CODE_COL, C.DATE_COL]).reset_index(drop=True)
    df["OC"] = df["C"] / df["O"] - 1
    df["ret1"] = df.groupby(C.CODE_COL)["AdjC"].pct_change(1)
    df["ret5"] = df.groupby(C.CODE_COL)["AdjC"].pct_change(5)
    df["ret21"] = df.groupby(C.CODE_COL)["AdjC"].pct_change(21)
    return df


def add_target(df: pd.DataFrame) -> pd.DataFrame:
    """翌日の寄り引けリターン Target を付与。"""
    df["NextO"] = df.groupby(C.CODE_COL)["O"].shift(-1)
    df["NextC"] = df.groupby(C.CODE_COL)["C"].shift(-1)
    df["Target"] = df["NextC"] / df["NextO"] - 1
    return df


def add_universe(df: pd.DataFrame, top_n: int = C.TOP_N) -> pd.DataFrame:
    """各 Date 内の売買代金ランクで TOP_N をユニバースとしてマーク。"""
    df["Turnover"] = detect_turnover(df)
    df["TurnoverRank"] = df.groupby(C.DATE_COL)["Turnover"].rank(ascending=False, method="first")
    df["InUniverse"] = df["TurnoverRank"] <= top_n
    return df


# ----------------------------------------------------------------- US market
def get_sp500_cc(start: str, end: str, ticker: str = C.SP500_TICKER) -> pd.DataFrame:
    """yfinance で S&P500 を取得し CLOSE-CLOSE 騰落率を返す（Date, SP500_cc）。要ネットワーク。"""
    import yfinance as yf
    sp = yf.download(ticker, start=start, end=end, auto_adjust=False, progress=False)
    if isinstance(sp.columns, pd.MultiIndex):
        sp.columns = sp.columns.get_level_values(0)
    sp = sp[["Close"]].rename(columns={"Close": "SP500_Close"}).reset_index()
    sp = sp.rename(columns={"Date": C.DATE_COL})
    sp = normalize_date(sp).sort_values(C.DATE_COL).reset_index(drop=True)
    sp["SP500_cc"] = sp["SP500_Close"].pct_change(1)
    return sp.dropna(subset=["SP500_cc"])[[C.DATE_COL, "SP500_cc"]].reset_index(drop=True)


def merge_sp500(df: pd.DataFrame, sp: pd.DataFrame) -> pd.DataFrame:
    """各日本取引日に「厳密に前の米国営業日」の CLOSE-CLOSE リターンを割り当てる。"""
    jp_dates = pd.DataFrame({C.DATE_COL: np.sort(df[C.DATE_COL].unique())})
    mkt = pd.merge_asof(jp_dates, sp.sort_values(C.DATE_COL), on=C.DATE_COL,
                        direction="backward", allow_exact_matches=False)
    return df.merge(mkt, on=C.DATE_COL, how="left")


# --------------------------------------------------------------- full panel
def build_panel(price, stock_list, alert, sp=None) -> pd.DataFrame:
    """3 入力（+S&P500）からモデル用パネルを構築する。"""
    df = price.copy().sort_values([C.CODE_COL, C.DATE_COL]).reset_index(drop=True)
    df = add_universe(df)
    df = merge_margin(df, stock_list)
    df = merge_short_restriction(df, alert)
    df = add_features(df)
    df = add_target(df)
    if sp is not None:
        df = merge_sp500(df, sp)
    return df


# --------------------------------------------------------------- positions
def compute_positions(group: pd.DataFrame, feature: str, direction: int = C.DIRECTION) -> pd.Series:
    """ある日のユニバース行に対するポジション（+1/-1/0）を返す。
    - position = direction * sign(feature)
    - ショート(pos<0)かつ売り禁ならフラット(0)
    """
    pos = direction * np.sign(group[feature])
    restricted = is_short_restricted(group["RestrictedByJSF"])
    return pos.where(~((pos < 0) & restricted), 0.0)


def daily_returns_for_feature(data: pd.DataFrame, feat: str, direction: int = C.DIRECTION) -> pd.Series:
    """各日付について ユニバース等加重の日次戦略リターンを返す。"""
    d = data[[C.DATE_COL, feat, "Target", "RestrictedByJSF"]].dropna(subset=[feat, "Target"]).copy()
    d["pos"] = compute_positions(d, feat, direction)
    d["pnl"] = d["pos"] * d["Target"]
    return d.groupby(C.DATE_COL)["pnl"].mean().sort_index()


def filter_regime(panel: pd.DataFrame, regime: str) -> pd.DataFrame:
    """市況レジームでパネルを絞る: all / up / down。"""
    if regime == "up":
        return panel[panel["SP500_cc"] > 0]
    if regime == "down":
        return panel[panel["SP500_cc"] < 0]
    return panel
