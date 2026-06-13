"""ペーパーアカウント(仮想口座)でのテスト運用エンジン.

日本のセクターETFを扱える証券会社のペーパートレードAPIは実質的に存在しないため、
ここでは仮想資金を持つシミュレート口座を実装する。毎営業日に呼び出すと:

  1. 最新の米国セクター当日リターンから日本セクター翌日リターンを予測
  2. 目標ウェイトを計算し、翌営業日の寄り付きでリバランス(シミュレート約定)
  3. 引けでマーク・トゥ・マーケットし、P&Lと建玉を記録
  4. 口座状態を JSON に永続化(cron等で日次運用できる)

実際のブローカー(例: Alpaca のペーパー口座)に接続したい場合は ``BrokerAdapter``
を実装して差し替える。Alpaca 用の雛形 ``AlpacaPaperBroker`` を同梱(米国ETF版。
日本ETFはAlpaca非対応のため、実運用では国内証券のAPI等に置き換える前提)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import to_weights
from .config import StrategyConfig
from .data import MarketData
from .signal import predict_next_day_jp


@dataclass
class AccountState:
    cash: float
    equity: float
    initial_equity: float
    positions: dict          # ticker -> notional(円) (ロング正/ショート負)
    history: list            # [{date, equity, ret, turnover}]
    last_weights: dict       # ticker -> weight

    @classmethod
    def new(cls, initial: float) -> "AccountState":
        return cls(cash=initial, equity=initial, initial_equity=initial,
                   positions={}, history=[], last_weights={})


class PaperAccount:
    """仮想口座. 状態は JSON ファイルに保存。"""

    def __init__(self, state_path: str | Path, initial_equity: float = 1_000_000.0):
        self.state_path = Path(state_path)
        if self.state_path.exists():
            self.state = AccountState(**json.loads(self.state_path.read_text()))
        else:
            self.state = AccountState.new(initial_equity)

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(asdict(self.state),
                                              ensure_ascii=False, indent=2))

    def step(self, date, target_weights: dict[str, float],
             realized_returns: dict[str, float], cost_bps: float) -> dict:
        """1営業日を進める。

        target_weights : 当日寄り付きでのリバランス目標(Σ|w| = グロス)。
        realized_returns: その建玉が当日引けまでに実現したリターン(始値→終値)。
        """
        prev_w = self.state.last_weights
        tickers = sorted(set(target_weights) | set(prev_w))
        turnover = sum(abs(target_weights.get(tk, 0.0) - prev_w.get(tk, 0.0))
                       for tk in tickers)

        # ポートフォリオ実現リターン(グロスエクスポージャー基準)
        port_ret = sum(target_weights.get(tk, 0.0) * realized_returns.get(tk, 0.0)
                       for tk in tickers)
        cost = turnover * cost_bps / 1e4
        net_ret = port_ret - cost

        new_equity = self.state.equity * (1 + net_ret)
        self.state.positions = {
            tk: w * new_equity for tk, w in target_weights.items() if abs(w) > 1e-9
        }
        self.state.equity = new_equity
        self.state.last_weights = dict(target_weights)
        rec = {
            "date": str(pd.Timestamp(date).date()),
            "equity": round(new_equity, 2),
            "ret": round(net_ret, 6),
            "turnover": round(turnover, 4),
            "cost": round(cost, 6),
        }
        self.state.history.append(rec)
        return rec

    def report(self) -> str:
        s = self.state
        n = len(s.history)
        total_ret = s.equity / s.initial_equity - 1
        rets = pd.Series([h["ret"] for h in s.history]) if n else pd.Series(dtype=float)
        sharpe = (rets.mean() / rets.std(ddof=1) * np.sqrt(252)
                  if n > 1 and rets.std(ddof=1) > 0 else float("nan"))
        lines = [
            "===== ペーパーアカウント運用レポート =====",
            f"初期資金        : {s.initial_equity:,.0f} 円",
            f"現在評価額      : {s.equity:,.0f} 円",
            f"累積リターン    : {total_ret*100:+.2f} %",
            f"運用日数        : {n}",
            f"R/R(年率, 参考) : {sharpe:.2f}",
        ]
        if s.positions:
            lines.append("--- 現在の建玉(円, ロング+/ショート-) ---")
            for tk, v in sorted(s.positions.items(), key=lambda x: -abs(x[1])):
                lines.append(f"   {tk:10s}: {v:+12,.0f}")
        return "\n".join(lines)


def run_paper_simulation(data: MarketData, cfg: StrategyConfig,
                         state_path: str | Path,
                         n_days: int = 60,
                         initial_equity: float = 1_000_000.0,
                         reset: bool = True,
                         variant: str = "shrink") -> PaperAccount:
    """直近 ``n_days`` 営業日を仮想口座で運用するシミュレーション。"""
    sp = Path(state_path)
    if reset and sp.exists():
        sp.unlink()
    acct = PaperAccount(sp, initial_equity=initial_equity)

    us = data.us_cc.values
    jp = data.jp_oc.values
    dates = data.dates
    T = len(dates)
    Wn = cfg.window
    jp_cols = list(data.jp_oc.columns)

    start = max(Wn, T - 1 - n_days)
    for t in range(start, T - 1):
        us_window = us[t - Wn:t]
        jp_window_next = jp[t - Wn + 1:t + 1]
        pred = predict_next_day_jp(us[t - Wn:t], jp_window_next, us[t],
                                   lam=cfg.lam, k=cfg.n_factors, variant=variant)
        w = to_weights(pred, cfg)
        target = {jp_cols[i]: float(w[i]) for i in range(len(jp_cols))}
        realized = {jp_cols[i]: float(jp[t + 1][i]) for i in range(len(jp_cols))}
        acct.step(dates[t + 1], target, realized, cfg.cost_bps)
    acct.save()
    return acct


# --------------------------------------------------------------------------- #
# 実ブローカー接続用の雛形 (ネットワーク + APIキーがある環境で利用)
# --------------------------------------------------------------------------- #
class BrokerAdapter:
    """実ブローカー接続のインターフェース。"""

    def get_equity(self) -> float: ...
    def get_positions(self) -> dict[str, float]: ...
    def submit_target_weights(self, weights: dict[str, float]) -> None: ...


class AlpacaPaperBroker(BrokerAdapter):
    """Alpaca ペーパー口座アダプタ(雛形, 要 alpaca-py + APIキー).

    注: Alpaca は米国株/ETFのみ。日本セクターETFは扱えないため、実運用では
    本クラスを国内証券のAPI等に置き換えること。米国ETFで戦略を回す場合の参考。
    環境変数 APCA_API_KEY_ID / APCA_API_SECRET_KEY を使用。
    """

    def __init__(self) -> None:  # pragma: no cover - 雛形
        try:
            from alpaca.trading.client import TradingClient
        except ImportError as e:
            raise RuntimeError("pip install alpaca-py が必要です") from e
        import os
        self.client = TradingClient(
            os.environ["APCA_API_KEY_ID"],
            os.environ["APCA_API_SECRET_KEY"],
            paper=True,
        )

    def get_equity(self) -> float:  # pragma: no cover
        return float(self.client.get_account().equity)

    def get_positions(self) -> dict[str, float]:  # pragma: no cover
        return {p.symbol: float(p.market_value) for p in self.client.get_all_positions()}

    def submit_target_weights(self, weights: dict[str, float]) -> None:  # pragma: no cover
        raise NotImplementedError(
            "目標ウェイト -> 株数換算 -> 発注 を環境に合わせて実装してください。"
        )
