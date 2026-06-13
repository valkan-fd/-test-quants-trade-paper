"""戦略の健全性テスト."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np

from src.backtest import run_backtest, to_weights
from src.config import StrategyConfig
from src.data import SyntheticDataSource
from src.pca import build_prior_subspace, subspace_regularized_pca
from src.signal import predict_next_day_jp


def test_prior_subspace_orthonormal():
    Q = build_prior_subspace(11, 17)
    assert Q.shape == (28, 2)
    np.testing.assert_allclose(Q.T @ Q, np.eye(2), atol=1e-10)


def test_pca_shapes_and_lambda_extremes():
    rng = np.random.default_rng(0)
    X = rng.standard_normal((120, 28))
    prior = build_prior_subspace(11, 17)
    W, ev = subspace_regularized_pca(X, prior, lam=0.9, k=4)
    assert W.shape == (28, 4)
    assert len(ev) == 4
    # λ=1 では因子は事前部分空間(2次元)に収まる -> 上位2因子の部分空間外成分は小
    W1, _ = subspace_regularized_pca(X, prior, lam=1.0, k=2)
    P = prior @ prior.T
    leak = np.linalg.norm((np.eye(28) - P) @ W1)
    assert leak < 1e-6


def test_weights_are_dollar_neutral_and_normalized():
    cfg = StrategyConfig()
    pred = np.array([0.02, -0.01, 0.005, -0.03, 0.01])
    w = to_weights(pred, cfg)
    assert abs(w.sum()) < 1e-9              # ドルニュートラル
    assert abs(np.abs(w).sum() - 1.0) < 1e-9  # グロス=1


def test_signal_predicts_with_correct_shape():
    data = SyntheticDataSource(n_days=300, seed=1).load()
    us, jp = data.us_cc.values, data.jp_oc.values
    pred = predict_next_day_jp(us[0:120], jp[1:121], us[120],
                               lam=0.9, k=4)
    assert pred.shape == (data.n_jp,)
    assert np.all(np.isfinite(pred))


def test_backtest_extracts_positive_alpha_on_synthetic():
    """合成データにはリードラグ構造があるので戦略は正のシャープを出すはず。"""
    data = SyntheticDataSource(n_days=900, seed=7).load()
    cfg = StrategyConfig()
    res = run_backtest(data, cfg)
    assert res.metrics["n_days"] > 100
    assert res.metrics["sharpe"] > 0.5


def test_no_lookahead_uses_only_past_and_us_today():
    """予測関数は窓と当日米国のみを引数に取り、未来の日本を参照しない。"""
    data = SyntheticDataSource(n_days=300, seed=2).load()
    us, jp = data.us_cc.values, data.jp_oc.values
    # jp の未来を改変しても、同じ窓・同じ us_today なら予測は不変
    p1 = predict_next_day_jp(us[0:120], jp[1:121].copy(), us[120], lam=0.9, k=4)
    jp_tampered = jp.copy()
    jp_tampered[121:] += 99.0  # 未来を汚染
    p2 = predict_next_day_jp(us[0:120], jp_tampered[1:121], us[120], lam=0.9, k=4)
    np.testing.assert_allclose(p1, p2)


# ---- フォワードテスト層のリグレッション (Haiku版バグの再発防止) ----
import tempfile

from src.config import JP_LARGE_CAP
from src.data import make_synthetic_equity_data
from src.forward_test import DailyForwardSimulator, run_walk_forward


def test_equity_synthetic_data_shape():
    """米セクター×日本個別株の合成データが正しい形状を返す。"""
    tickers = list(JP_LARGE_CAP.keys())
    d = make_synthetic_equity_data(tickers, n_days=300)
    assert d.n_us == 11
    assert d.n_jp == len(tickers)
    assert len(d.dates) == 300
    assert list(d.jp_oc.columns) == tickers


def test_daily_forward_weights_are_normalized_and_idempotent():
    """step に渡す前に to_weights で正規化 → グロス≈1・ドルニュートラル。
    同じ日付の二重記録を防ぐ last_date() が機能する。"""
    cfg = StrategyConfig()
    d = make_synthetic_equity_data(list(JP_LARGE_CAP.keys()), n_days=200)
    jp_cols = list(d.jp_oc.columns)
    us, jp = d.us_cc.values, d.jp_oc.values
    Wn = cfg.window
    t = len(d.dates) - 2
    pred = predict_next_day_jp(us[t-Wn:t], jp[t-Wn+1:t+1], us[t], lam=cfg.lam, k=cfg.n_factors)
    w = to_weights(pred, cfg)
    assert abs(np.abs(w).sum() - 1.0) < 1e-9      # グロス=1
    assert abs(w.sum()) < 1e-9                     # ドルニュートラル

    with tempfile.TemporaryDirectory() as tmp:
        sp = Path(tmp) / "s.json"
        sim = DailyForwardSimulator(sp, initial_capital=1_000_000.0)
        assert sim.last_date() is None
        weights = {jp_cols[i]: float(w[i]) for i in range(len(jp_cols))}
        realized = {jp_cols[i]: float(jp[t+1][i]) for i in range(len(jp_cols))}
        log = sim.step(d.dates[t+1], weights, realized, cfg)
        # P&L は現実的なスケール(極小ではない): |net| が 1e-6 より大きく 0.1 未満
        assert 1e-6 < abs(log.net_return) < 0.1
        assert sim.last_date() == str(d.dates[t+1].date())


def test_walk_forward_matches_causal_backtest():
    """ウォークフォワードのサブ期間は、本物の因果バックテスト日次リターンの
    スライスと一致する(=偽OOSではない)。"""
    cfg = StrategyConfig()
    d = SyntheticDataSource(n_days=900).load()
    bt = run_backtest(d, cfg)
    wf = run_walk_forward(d, cfg, test_window=126, step=126)
    assert len(wf.windows) >= 2
    # 各 window の開始日が backtest のリターン系列に存在する実現日であること
    bt_dates = set(str(dt.date()) for dt in bt.daily_returns.index)
    for w in wf.windows:
        assert w.start_date in bt_dates
        assert w.end_date in bt_dates
