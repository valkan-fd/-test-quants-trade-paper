"""フォワードテスト・フレームワーク（ウォークフォワードOOS + 毎日ペーパー）.

このモジュールは2つの層を提供する:

1. ウォークフォワードOOS (WalkForwardBacktest)
   ├─ training window [t0, t0+W)
   └─ test/OOS window [t0+W, t0+W+T)  <- 学習後の「未来」だけでテスト
   → 進めながら window をスライド → 複数期間のOOSパフォーマンスを記録

2. 毎日ペーパー運用 (DailyForwardSimulator)
   ├─ 毎日cronで呼び出し
   ├─ 最新データ確認 → モデル更新 → 寄りで仮想約定 → 引けでマーク
   └─ JSON に累積ログ＆詳細指標を記録（戦略改善に必要なディテール付き）

構造:
  - BacktestWindow（期間内の1スナップショット）
  - WalkForwardBacktest（複数Window → デフレーション測定）
  - DailyForwardLog（日次の詳細記録）
  - DailyForwardSimulator（毎営業日の約定・更新）
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pandas as pd

from .config import StrategyConfig
from .data import MarketData
from .backtest import run_backtest, compute_metrics
from .signal import predict_next_day_jp


class BacktestWindow(NamedTuple):
    """特定期間のバックテスト結果スナップショット."""
    start_date: str
    end_date: str
    metrics: dict  # annual_return, annual_vol, sharpe, max_drawdown, ...
    n_trades: int
    avg_turnover: float


@dataclass
class WalkForwardResult:
    """ウォークフォワードOOSの全体サマリ."""
    windows: list[BacktestWindow]
    overall_metrics: dict

    def summary(self) -> str:
        """複数期間のOOS結果を比較表示."""
        lines = [
            "===== ウォークフォワード OOS 結果 =====",
            f"テスト期間数: {len(self.windows)}",
            "",
            "期間別パフォーマンス:",
        ]
        for w in self.windows:
            lines.append(
                f"  {w.start_date}〜{w.end_date}: "
                f"年率{w.metrics['annual_return']*100:6.2f}% "
                f"R/R={w.metrics['sharpe']:5.2f} "
                f"MDD={w.metrics['max_drawdown']*100:6.2f}% ({w.n_trades}trades)"
            )
        lines.extend([
            "",
            "全体統計（期間内での平均・最小・最大）:",
            f"  年率リターン   : "
            f"avg={self.overall_metrics['annual_return_mean']*100:6.2f}% "
            f"min={self.overall_metrics['annual_return_min']*100:6.2f}% "
            f"max={self.overall_metrics['annual_return_max']*100:6.2f}%",
            f"  リスクリワード : "
            f"avg={self.overall_metrics['sharpe_mean']:5.2f} "
            f"min={self.overall_metrics['sharpe_min']:5.2f} "
            f"max={self.overall_metrics['sharpe_max']:5.2f}",
        ])
        return "\n".join(lines)


@dataclass
class DailyForwardLog:
    """1営業日のペーパー運用ログ（詳細）."""
    date: str
    signal_strength: float       # リードラグ予測シグナルの大きさ（ノルム）
    factor_scores: list[float]   # 抽出された因子スコア（各成分）
    weights: dict               # 銘柄別ウェイト {ticker: w}
    realized_return: float      # 実現リターン（グロス）
    turnover: float
    transaction_cost: float
    net_return: float           # グロス - コスト
    equity: float
    max_pos: str                # 最大ロングポジション銘柄
    max_pos_weight: float


@dataclass
class DailyForwardSimulatorState:
    """ペーパー運用の永続状態."""
    initial_capital: float
    current_equity: float
    last_weights: dict = field(default_factory=dict)
    logs: list[DailyForwardLog] = field(default_factory=list)


def run_walk_forward(
    data: MarketData,
    cfg: StrategyConfig,
    train_window: int = 252,      # 互換のため残置(現状では未使用)
    test_window: int = 63,         # 期間分割の長さ(営業日)
    step: int = 63,                # 期間を進める幅(営業日)
) -> WalkForwardResult:
    """ウォークフォワード(期間外)検証.

    本戦略は「各営業日 t で過去窓のみから推定し翌日 t+1 を予測する」完全な因果
    (causal)バックテストであり、構造的にすべての取引が期間外(OOS)である。
    そこでまず全期間の因果バックテストを1回実行し、その日次リターンを test_window
    ごとのサブ期間に分割して、期間別の安定性(regime依存性)を測定する。

    これにより「学習後の未来だけで評価する」OOSの趣旨を、リークなく正しく実現する。
    """
    bt = run_backtest(data, cfg)
    rets = bt.daily_returns          # index=実現日(t+1)
    turn = bt.turnover
    windows: list[BacktestWindow] = []

    n = len(rets)
    for s in range(0, n - test_window + 1, step):
        seg_rets = rets.iloc[s:s + test_window]
        seg_turn = turn.iloc[s:s + test_window]
        if len(seg_rets) < 2:
            continue
        seg_metrics = compute_metrics(seg_rets, seg_turn, cfg)
        windows.append(BacktestWindow(
            start_date=str(seg_rets.index[0].date()),
            end_date=str(seg_rets.index[-1].date()),
            metrics=seg_metrics,
            n_trades=len(seg_rets),
            avg_turnover=float(seg_turn.mean()),
        ))

    # 全体統計
    if windows:
        rets = [w.metrics['annual_return'] for w in windows]
        sharpes = [w.metrics['sharpe'] for w in windows]
        overall = {
            'annual_return_mean': float(np.mean(rets)),
            'annual_return_min': float(np.min(rets)),
            'annual_return_max': float(np.max(rets)),
            'sharpe_mean': float(np.mean(sharpes)),
            'sharpe_min': float(np.min(sharpes)),
            'sharpe_max': float(np.max(sharpes)),
        }
    else:
        overall = {}

    return WalkForwardResult(windows=windows, overall_metrics=overall)


class DailyForwardSimulator:
    """毎日cronで実行するペーパー運用エンジン.

    状態は JSON に永続化。毎営業日呼び出すたびに：
    1. 最新データ取得
    2. モデル（直近120営業日の結合相関）を更新
    3. 米国当日→日本翌日シグナル算出
    4. 寄り（MOO）でリバランス＆約定
    5. 引け（MOC）でマーク・ログ保存
    """

    def __init__(self, state_path: str | Path, initial_capital: float = 1_000_000.0):
        self.state_path = Path(state_path)
        if self.state_path.exists():
            data = json.loads(self.state_path.read_text())
            self.state = DailyForwardSimulatorState(
                initial_capital=data['initial_capital'],
                current_equity=data['current_equity'],
                last_weights=data.get('last_weights', {}),
                logs=[DailyForwardLog(**log) if isinstance(log, dict) else log
                      for log in data.get('logs', [])]
            )
        else:
            self.state = DailyForwardSimulatorState(
                initial_capital=initial_capital,
                current_equity=initial_capital
            )

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(self.state)
        # DailyForwardLog を dict にシリアライズ
        data['logs'] = [asdict(log) if isinstance(log, DailyForwardLog) else log
                        for log in data.get('logs', [])]
        self.state_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str))

    def last_date(self) -> str | None:
        """最後に記録した営業日(YYYY-MM-DD)。未記録なら None。冪等性判定に使う。"""
        return self.state.logs[-1].date if self.state.logs else None

    def step(self, date: pd.Timestamp, weights: dict[str, float],
             realized: dict[str, float], cfg: StrategyConfig,
             signal_strength: float = 0.0,
             factor_scores: list[float] | None = None) -> DailyForwardLog:
        """1営業日を約定・記録する.

        Parameters
        ----------
        date     : 約定日（寄りで建玉、引けでマーク）
        weights  : **正規化済み** 目標ウェイト {ticker: w}（呼び出し側で to_weights 済み。
                   ドルニュートラル・グロス=1 を前提）。
        realized : その建玉が当日引けまでに実現したリターン {ticker: 始値→終値リターン}
        cfg      : 戦略設定（取引コスト等）
        signal_strength : 予測シグナルのノルム（ログ用）
        factor_scores   : 因子スコア（ログ用）
        """
        weights_dict = {tk: float(w) for tk, w in weights.items()}

        # ターンオーバー（前日ウェイトとの差の絶対値和）
        prev_w = self.state.last_weights
        turnover = sum(abs(weights_dict.get(tk, 0.0) - prev_w.get(tk, 0.0))
                       for tk in set(weights_dict) | set(prev_w))

        # ポートフォリオ実現リターン（グロス）
        port_ret = sum(weights_dict.get(tk, 0.0) * realized.get(tk, 0.0)
                       for tk in weights_dict)
        cost = turnover * cfg.cost_bps / 1e4
        net_ret = port_ret - cost

        new_equity = self.state.current_equity * (1 + net_ret)
        self.state.current_equity = new_equity
        self.state.last_weights = dict(weights_dict)

        nonzero = {tk: w for tk, w in weights_dict.items() if abs(w) > 1e-12}
        log = DailyForwardLog(
            date=str(pd.Timestamp(date).date()),
            signal_strength=float(signal_strength),
            factor_scores=factor_scores or [],
            weights=nonzero,
            realized_return=float(port_ret),
            turnover=float(turnover),
            transaction_cost=float(cost),
            net_return=float(net_ret),
            equity=float(new_equity),
            max_pos=max(nonzero, key=lambda tk: abs(nonzero[tk])) if nonzero else "N/A",
            max_pos_weight=float(max(abs(w) for w in nonzero.values())) if nonzero else 0.0,
        )
        self.state.logs.append(log)
        return log

    def report(self) -> str:
        logs = self.state.logs
        n = len(logs)
        total_ret = self.state.current_equity / self.state.initial_capital - 1
        rets = [log.net_return for log in logs]
        rets_s = pd.Series(rets) if rets else pd.Series(dtype=float)
        sharpe = (rets_s.mean() / rets_s.std(ddof=1) * np.sqrt(252)
                  if len(rets) > 1 and rets_s.std(ddof=1) > 1e-12 else float('nan'))
        lines = [
            "===== フォワード・ペーパー運用レポート =====",
            f"初期資金      : {self.state.initial_capital:,.0f} 円",
            f"現在評価額    : {self.state.current_equity:,.0f} 円",
            f"累積リターン  : {total_ret*100:+.2f} %",
            f"運用日数      : {n}",
            f"R/R(年率,参考): {sharpe:.2f}",
            "",
            "--- 直近5営業日 ---",
        ]
        for log in logs[-5:]:
            lines.append(f"  {log.date}: ret={log.net_return*100:+.3f}% "
                        f"TO={log.turnover:.3f} {log.max_pos}:{log.max_pos_weight:+.4f}")
        return "\n".join(lines)
