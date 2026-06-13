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
