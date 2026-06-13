"""戦略の設定値とETFユニバース定義.

論文「部分空間正則化付き主成分分析を用いた日米業種リードラグ投資戦略」
(JSAI SIG-FIN FIN-036, 2026, pp.76-83) の手法を再構成するための設定.

注意: 論文PDF本体(J-Stage)は取得できなかったため(403)、アブストラクトおよび
公開された詳細解説記事から再構成したパラメータである。実データでの再現時は
これらの値を論文・自分の検証に合わせて調整すること。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# --- 米国セクターETF (SPDR Select Sector, 終値→終値リターンを情報集合に使う) ---
US_SECTOR_ETFS: dict[str, str] = {
    "XLB": "素材",
    "XLC": "通信サービス",
    "XLE": "エネルギー",
    "XLF": "金融",
    "XLI": "資本財",
    "XLK": "情報技術",
    "XLP": "生活必需品",
    "XLRE": "不動産",
    "XLU": "公益",
    "XLV": "ヘルスケア",
    "XLY": "一般消費財",
}

# --- 日本セクターETF (NEXT FUNDS TOPIX-17シリーズ, 翌日の始値→終値リターンが予測対象) ---
JP_SECTOR_ETFS: dict[str, str] = {
    "1617.T": "食品",
    "1618.T": "エネルギー資源",
    "1619.T": "建設・資材",
    "1620.T": "素材・化学",
    "1621.T": "医薬品",
    "1622.T": "自動車・輸送機",
    "1623.T": "鉄鋼・非鉄",
    "1624.T": "機械",
    "1625.T": "電機・精密",
    "1626.T": "情報通信・サービスその他",
    "1627.T": "電力・ガス",
    "1628.T": "運輸・物流",
    "1629.T": "商社・卸売",
    "1630.T": "小売",
    "1631.T": "銀行",
    "1632.T": "金融(除く銀行)",
    "1633.T": "不動産",
}


@dataclass
class StrategyConfig:
    # --- 部分空間正則化付きPCA ---
    lam: float = 0.9          # 部分空間への縮小強度 λ (論文では強い縮小=0.9)
    n_factors: int = 4        # 抽出する主成分(ファクター)数 k
    window: int = 120         # ローリング窓(営業日)

    # --- ポートフォリオ ---
    gross_exposure: float = 1.0   # グロスエクスポージャー(Σ|w|)
    market_neutral: bool = True   # 業種横断でデマーン(ドルニュートラル)
    long_short: bool = True       # ロング・ショート(False ならロングオンリー上位)
    top_k_positions: int | None = None  # Noneなら全業種に連続ウェイト

    # --- コスト/運用 ---
    cost_bps: float = 5.0     # 片道取引コスト(bps). 往復はturnover*cost
    trading_days: int = 252

    # --- 再現用シード(合成データ) ---
    seed: int = 42

    def prior_factor_names(self) -> list[str]:
        return ["global", "country_spread"][: max(0, min(2, self.n_factors))]


DEFAULT_CONFIG = StrategyConfig()
