"""部分空間正則化付き主成分分析 (Subspace-Regularized PCA).

論文の中核手法。素のローリングPCAは短窓では固有ベクトル(エクスポージャー)が
時点ごとに大きく振れ、経済的解釈の一貫性・推定の安定性が損なわれる。そこで
「事前に経済的意味を与えた部分空間」へ強い縮小(λ)をかけて安定化する。

事前部分空間(prior subspace)の基底:
  - global        : 全銘柄に等ウェイト (= マーケット全体の方向)
  - country_spread: 米国側を正・日本側を負 (= 日米格差の方向)

定式化(再構成):
  相関行列 S に対し、事前部分空間への射影子 P を用いて
      S_reg = (1 - λ) · S + λ · (P S P)
  を構成し、その上位固有ベクトルを因子ローディングとして採用する。
  λ→1 で因子は事前部分空間(2次元)へ完全に縮小され、λ→0 で素のPCAに一致する。
  λ=0.9 は「強い縮小で短窓推定を安定化」という論文の記述に対応。

注意: 論文PDF本体は取得できなかったため(403)、上式は公開情報からの忠実な
再構成である。`variant` 引数で penalty 形式 (S + λ·c·P) も選べる。
"""
from __future__ import annotations

import numpy as np


def build_prior_subspace(n_us: int, n_jp: int) -> np.ndarray:
    """事前部分空間の正規直交基底 (n x 2) を返す。

    列0: global (全銘柄等ウェイト), 列1: country_spread (米+ / 日-).
    """
    n = n_us + n_jp
    g = np.ones(n)
    c = np.concatenate([np.ones(n_us) / n_us, -np.ones(n_jp) / n_jp])
    B = np.column_stack([g, c]).astype(float)
    Q, _ = np.linalg.qr(B)   # 正規直交化
    return Q


def subspace_regularized_pca(
    window_returns: np.ndarray,
    prior_basis: np.ndarray,
    lam: float,
    k: int,
    variant: str = "shrink",
) -> tuple[np.ndarray, np.ndarray]:
    """部分空間正則化付きPCA.

    Parameters
    ----------
    window_returns : (T, n) 標準化済みリターン窓.
    prior_basis    : (n, m) 事前部分空間の正規直交基底.
    lam            : 縮小強度 λ ∈ [0, 1].
    k              : 取り出す主成分数.
    variant        : "shrink" -> (1-λ)S + λ PSP, "penalty" -> S + λ·tr(S)/n·P.

    Returns
    -------
    W       : (n, k) 因子ローディング(上位固有ベクトル, 降順).
    eigvals : (k,)  対応する固有値.
    """
    # 相関行列(列=銘柄)。標準化済み前提だが念のため相関で評価。
    S = np.corrcoef(window_returns, rowvar=False)
    S = np.nan_to_num(S, nan=0.0)
    n = S.shape[0]

    P = prior_basis @ prior_basis.T   # 事前部分空間への射影子

    if variant == "shrink":
        M = (1.0 - lam) * S + lam * (P @ S @ P)
    elif variant == "penalty":
        c = np.trace(S) / n
        M = S + lam * c * P
    else:
        raise ValueError(f"unknown variant: {variant}")

    M = (M + M.T) / 2.0   # 数値対称化
    eigvals, eigvecs = np.linalg.eigh(M)   # 昇順
    order = np.argsort(eigvals)[::-1][:k]
    return eigvecs[:, order], eigvals[order]
