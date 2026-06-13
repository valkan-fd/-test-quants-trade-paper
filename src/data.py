"""データ層.

2種類のソースを提供する:

1. ``SyntheticDataSource`` — このサンドボックス環境(市場データの外部取得が
   ネットワークでブロックされている)でパイプライン全体を end-to-end で動かす
   ための、リードラグ構造を仕込んだ合成データ生成器。

2. ``YFinanceDataSource`` — ネットワークが使えるローカル環境で、実際の米国/日本
   セクターETFの価格を取得して論文結果の再現を試みるためのアダプタ。
   (yfinance が必要: ``pip install yfinance``)

いずれも以下を返す:
- ``us_cc``: 米国セクターETF 終値→終値リターン (DataFrame: index=日付, col=ティッカー)
- ``jp_oc``: 日本セクターETF 始値→終値リターン (DataFrame: index=日付, col=ティッカー)

リードラグの定義: ある営業日 t の ``us_cc[t]`` が、翌営業日 ``jp_oc[t+1]`` を予測する。
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import JP_SECTOR_ETFS, US_SECTOR_ETFS


@dataclass
class MarketData:
    us_cc: pd.DataFrame   # 米国セクター 終値→終値リターン
    jp_oc: pd.DataFrame   # 日本セクター 始値→終値リターン

    @property
    def n_us(self) -> int:
        return self.us_cc.shape[1]

    @property
    def n_jp(self) -> int:
        return self.jp_oc.shape[1]

    @property
    def dates(self) -> pd.DatetimeIndex:
        return self.us_cc.index


class SyntheticDataSource:
    """リードラグ構造を持つ合成市場データ.

    潜在ファクター f_t が「当日の米国(us_cc[t])」と「翌日の日本(jp_oc[t+1])」の
    双方を駆動するように設計してある。したがって us_cc[t] を観測すると f_t が
    部分的に推定でき、それが jp_oc[t+1] を予測する —— これが論文の仮説する
    「先に閉じた市場で確定した情報の遅延伝播」の合成版である。
    """

    def __init__(self, n_days: int = 1500, seed: int = 42,
                 leadlag_strength: float = 0.38, noise: float = 0.011):
        self.n_days = n_days
        self.seed = seed
        self.leadlag_strength = leadlag_strength
        self.noise = noise

    def load(self) -> MarketData:
        rng = np.random.default_rng(self.seed)
        us_tickers = list(US_SECTOR_ETFS)
        jp_tickers = list(JP_SECTOR_ETFS)
        n_us, n_jp = len(us_tickers), len(jp_tickers)
        T = self.n_days
        K = 5  # 潜在ファクター数

        # 潜在ファクター: 第1=グローバル(市場全体), 以降=セクターローテーション.
        # 軽い AR(1) 持続性を持たせ、遅延伝播を表現可能にする。
        f = np.zeros((T, K))
        phi = np.array([0.10, 0.05, 0.05, 0.04, 0.03])
        scale = np.array([1.0, 0.6, 0.5, 0.4, 0.35]) * 0.012
        for t in range(1, T):
            f[t] = phi * f[t - 1] + rng.standard_normal(K) * scale

        # ファクター・ローディング. 第1列は全て正(=グローバルファクター).
        B_us = rng.standard_normal((n_us, K)) * 0.7
        B_jp = rng.standard_normal((n_jp, K)) * 0.7
        B_us[:, 0] = np.abs(B_us[:, 0]) + 0.6   # グローバル: 全業種が正に反応
        B_jp[:, 0] = np.abs(B_jp[:, 0]) + 0.6

        # 米国 当日リターン: 当日のファクターで駆動
        us = f @ B_us.T + rng.standard_normal((T, n_us)) * self.noise

        # 日本 翌日リターン: 「前日の米国を駆動したファクター f[t]」で駆動する。
        # すなわち jp_oc[t+1] が f[t] に依存 => us_cc[t] が jp_oc[t+1] を予測。
        jp = np.zeros((T, n_jp))
        jp_idio = rng.standard_normal((T, n_jp)) * self.noise
        for t in range(T - 1):
            jp[t + 1] = self.leadlag_strength * (f[t] @ B_jp.T) + jp_idio[t + 1]
        jp[0] = jp_idio[0]

        idx = pd.bdate_range("2018-01-01", periods=T)
        us_cc = pd.DataFrame(us, index=idx, columns=us_tickers)
        jp_oc = pd.DataFrame(jp, index=idx, columns=jp_tickers)
        return MarketData(us_cc=us_cc, jp_oc=jp_oc)


class YFinanceDataSource:
    """実データ用アダプタ(要 yfinance, ネットワーク必須).

    米国: 終値→終値リターン (Close[t]/Close[t-1]-1)
    日本: 始値→終値リターン (Close[t]/Open[t]-1)
    """

    def __init__(self, start: str = "2018-01-01", end: str | None = None):
        self.start = start
        self.end = end

    def load(self) -> MarketData:
        try:
            import yfinance as yf
        except ImportError as e:  # pragma: no cover
            raise RuntimeError(
                "yfinance が必要です: pip install yfinance\n"
                "(注: このサンドボックス環境では市場データ取得がブロックされています。"
                "ローカル環境で実行してください)"
            ) from e

        us_tickers = list(US_SECTOR_ETFS)
        jp_tickers = list(JP_SECTOR_ETFS)

        us_raw = yf.download(us_tickers, start=self.start, end=self.end,
                             auto_adjust=True, progress=False)
        jp_raw = yf.download(jp_tickers, start=self.start, end=self.end,
                             auto_adjust=True, progress=False)

        us_close = us_raw["Close"][us_tickers]
        us_cc = us_close.pct_change().dropna(how="all")

        jp_close = jp_raw["Close"][jp_tickers]
        jp_open = jp_raw["Open"][jp_tickers]
        jp_oc = (jp_close / jp_open - 1.0).dropna(how="all")

        # 共通営業日に揃える(リードラグの t / t+1 整列は backtest 側で行う)
        common = us_cc.index.intersection(jp_oc.index)
        return MarketData(us_cc=us_cc.loc[common].ffill(),
                          jp_oc=jp_oc.loc[common].ffill())


def get_data_source(source: str, **kwargs):
    if source == "synthetic":
        return SyntheticDataSource(**kwargs)
    if source == "yfinance":
        return YFinanceDataSource(**kwargs)
    raise ValueError(f"unknown source: {source}")
