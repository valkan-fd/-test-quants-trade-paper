"""J-Quants からデータを取得して data/jquantsapi/v2/*_mod.parquet を作る。

⚠️ この環境ではネットワーク・認証情報が無いため未検証。公式の Python クライアント
   `jquants-api-client`（import 名 `jquantsapi`）の利用を前提に、現行ドキュメントで
   メソッド名・列名を必ず確認してから使うこと。

前提プラン: フォワードテストには「前営業日まで」取得できる有料プラン（ライト以上）が必要。
            無料プランは 12 週遅延のため使えない。

認証（環境変数）:
  - JQUANTS_REFRESH_TOKEN              （推奨。リフレッシュトークン）
  - もしくは JQUANTS_MAIL_ADDRESS / JQUANTS_PASSWORD
"""
from __future__ import annotations

import os

import pandas as pd

from . import config as C


# ----------------------------------------------------------------- client
def get_client():
    """環境変数から jquantsapi.Client を生成する。"""
    import jquantsapi  # pip install jquants-api-client

    rt = os.environ.get("JQUANTS_REFRESH_TOKEN")
    if rt:
        return jquantsapi.Client(refresh_token=rt)
    mail = os.environ.get("JQUANTS_MAIL_ADDRESS")
    pw = os.environ.get("JQUANTS_PASSWORD")
    if mail and pw:
        return jquantsapi.Client(mail_address=mail, password=pw)
    raise RuntimeError("JQUANTS_REFRESH_TOKEN もしくは JQUANTS_MAIL_ADDRESS/JQUANTS_PASSWORD を設定してください")


def _first_col(df: pd.DataFrame, candidates) -> str:
    for c in candidates:
        if c in df.columns:
            return c
    raise KeyError(f"列が見つかりません（候補: {candidates}） 実際の列: {list(df.columns)}")


# ----------------------------------------------------------------- prices
def fetch_prices(client, start: str, end: str) -> pd.DataFrame:
    """日次四本値を取得し O/H/L/C/V/AdjC/TurnoverValue 形式に整形する。

    jquantsapi: get_price_range(start_dt, end_dt) を想定。列名はドキュメントで要確認。
    """
    raw = client.get_price_range(start_dt=start, end_dt=end)
    out = pd.DataFrame({
        "Date": pd.to_datetime(raw[_first_col(raw, ["Date"])]),
        "Code": raw[_first_col(raw, ["Code", "LocalCode"])].astype(str),
        "O": raw[_first_col(raw, ["Open"])].astype(float),
        "H": raw[_first_col(raw, ["High"])].astype(float),
        "L": raw[_first_col(raw, ["Low"])].astype(float),
        "C": raw[_first_col(raw, ["Close"])].astype(float),
        "V": raw[_first_col(raw, ["Volume"])].astype(float),
        "AdjC": raw[_first_col(raw, ["AdjustmentClose", "AdjClose"])].astype(float),
        "TurnoverValue": raw[_first_col(raw, ["TurnoverValue"])].astype(float),
    })
    return out.sort_values(["Date", "Code"]).reset_index(drop=True)


# -------------------------------------------------------------- stock list
def fetch_stock_list(client) -> pd.DataFrame:
    """上場銘柄一覧を取得し Code/CompanyName/Mrgn（信用区分名）に整形する。

    jquantsapi: get_list() もしくは get_listed_info() を想定。
    """
    raw = client.get_list() if hasattr(client, "get_list") else client.get_listed_info()
    mrgn_col = _first_col(raw, ["MarginCodeName", "MarginCode", "Mrgn"])
    name_col = _first_col(raw, ["CompanyName", "CompanyNameJapanese", "Name"])
    out = pd.DataFrame({
        "Code": raw[_first_col(raw, ["Code", "LocalCode"])].astype(str),
        "CompanyName": raw[name_col].astype(str),
        "Mrgn": raw[mrgn_col].astype(str),
    })
    return out.drop_duplicates(subset=["Code"]).reset_index(drop=True)


# -------------------------------------------------- short restriction (売り禁)
def fetch_short_restriction(client, start: str, end: str) -> pd.DataFrame:
    """売り禁（RestrictedByJSF）の日々公表データを取得する。

    ⚠️ 要結線。この項目は日本証券金融(JSF)の貸借取引規制（申込停止/注意喚起）由来で、
       J-Quants のどのエンドポイントに対応するか確証がない。実ソースが確定したら、
       下の TODO を埋めて Date/Code/RestrictedByJSF（発生='1'/解除='0'）の疎な表を返すこと。

    例（実装候補）:
      - JSF 公表データ（貸借取引銘柄の規制措置）をスクレイプ／取得して整形
      - J-Quants の該当（プレミアム）エンドポイントがあればそれを利用

    暫定: 空表（=規制なし扱い）を返し、警告を出す。
    """
    # TODO: 実ソースに置き換える
    import warnings
    warnings.warn("fetch_short_restriction は未結線です（規制なし扱い）。実ソースを結線してください。")
    return pd.DataFrame(columns=["Date", "Code", "RestrictedByJSF"])


# ----------------------------------------------------------------- save all
def save_all(start: str, end: str, data_dir: str = C.DATA_DIR):
    """3 ファイルを取得して _mod.parquet として保存する。"""
    os.makedirs(data_dir, exist_ok=True)
    client = get_client()

    prices = fetch_prices(client, start, end)
    stock_list = fetch_stock_list(client)
    alert = fetch_short_restriction(client, start, end)

    prices.to_parquet(os.path.join(data_dir, "stock_prices_mod.parquet"), index=False)
    stock_list.to_parquet(os.path.join(data_dir, "stock_list_mod.parquet"), index=False)
    alert.to_parquet(os.path.join(data_dir, "margin_alert.parquet"), index=False)

    print(f"prices     : {prices.shape}  ({prices['Date'].min().date()} 〜 {prices['Date'].max().date()})")
    print(f"stock_list : {stock_list.shape}")
    print(f"alert      : {alert.shape}")
    return prices, stock_list, alert
