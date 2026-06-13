"""リードラグ予測シグナルの構成.

考え方(論文の仮説の実装):
  1. 過去窓について、米国当日リターン us_cc[i] と「翌日」日本リターン jp_oc[i+1]
     を横に連結した結合サンプル X_i = [z_us(i), z_jp(i+1)] を作る(標準化後)。
  2. この結合相関行列に部分空間正則化付きPCAをかけ、安定な因子ローディング
     W = [W_us; W_jp] (n_us+n_jp 行) を得る。
  3. 予測日 t では米国の当日リターン z_us(t) だけが観測できる。W_us から最小二乗で
     因子スコア f̂ を復元し、W_jp で日本側を再構成して翌日リターンを予測する:
         f̂ = argmin_f || W_us f - z_us(t) ||,   r̂_jp(t+1) = W_jp f̂
  これは「米国終値のセクター相対強弱ベクトルを、共通因子を介して翌朝の日本へ
  写像する」という論文の機構の忠実な実装である。
"""
from __future__ import annotations

import numpy as np

from .pca import build_prior_subspace, subspace_regularized_pca


class StandardScaler:
    """窓内の平均・標準偏差で標準化(列ごと)。fit した統計で transform する。"""

    def __init__(self) -> None:
        self.mean_: np.ndarray | None = None
        self.std_: np.ndarray | None = None

    def fit(self, X: np.ndarray) -> "StandardScaler":
        self.mean_ = X.mean(axis=0)
        self.std_ = X.std(axis=0)
        self.std_[self.std_ < 1e-12] = 1.0
        return self

    def transform(self, X: np.ndarray) -> np.ndarray:
        return (X - self.mean_) / self.std_

    def inverse_std(self, z: np.ndarray) -> np.ndarray:
        """標準化空間のリターンを元のスケールへ戻す(平均は足さない=超過方向)。"""
        return z * self.std_


def predict_next_day_jp(
    us_window: np.ndarray,    # (T, n_us)  窓内の米国当日リターン (i = t-T..t-1)
    jp_window_next: np.ndarray,  # (T, n_jp) 対応する翌日の日本リターン (i+1)
    us_today: np.ndarray,     # (n_us,)    予測日 t の米国当日リターン
    lam: float,
    k: int,
    variant: str = "shrink",
) -> np.ndarray:
    """予測日 t の日本セクター翌日リターン r̂_jp(t+1) を返す (元スケール, デマーン前)。"""
    n_us = us_window.shape[1]
    n_jp = jp_window_next.shape[1]

    # 米国と日本それぞれを窓統計で標準化
    sc_us = StandardScaler().fit(us_window)
    sc_jp = StandardScaler().fit(jp_window_next)
    z_us = sc_us.transform(us_window)
    z_jp = sc_jp.transform(jp_window_next)

    # 結合サンプル -> 部分空間正則化PCA
    joint = np.hstack([z_us, z_jp])               # (T, n_us+n_jp)
    prior = build_prior_subspace(n_us, n_jp)
    W, _ = subspace_regularized_pca(joint, prior, lam=lam, k=k, variant=variant)

    W_us = W[:n_us, :]    # (n_us, k)
    W_jp = W[n_us:, :]    # (n_jp, k)

    # 予測日の米国リターンを標準化し、因子スコアを最小二乗で復元
    z_us_today = sc_us.transform(us_today.reshape(1, -1)).ravel()
    f_hat, *_ = np.linalg.lstsq(W_us, z_us_today, rcond=None)   # (k,)

    # 日本側を再構成 -> 元スケールへ
    z_jp_pred = W_jp @ f_hat                       # (n_jp,) 標準化空間
    r_jp_pred = sc_jp.inverse_std(z_jp_pred)       # 元スケール
    return r_jp_pred
