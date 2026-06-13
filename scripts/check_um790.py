#!/usr/bin/env python3
"""UM790 セルフチェック — ペーパーテストが実際に回せるか検証する.

このサンドボックス環境では市場データ取得がネットワークでブロックされているため、
実データ経路(yfinance)はUM790等のローカルで検証する必要がある。
本スクリプトを UM790 で実行して、以下を順に確認する:

  1. Python / 依存パッケージ (numpy, pandas, scipy)
  2. yfinance のインストール
  3. 米国セクターETF (XLB等) の取得可否
  4. 日本個別株 (7203.T等) の取得可否
  5. 戦略パイプライン (予測→ウェイト) が end-to-end で動くか

すべて [OK] なら、cron でのペーパーテスト運用が可能。

用法:
  python scripts/check_um790.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OK = "[OK]  "
NG = "[NG]  "
INFO = "[--]  "


def main() -> int:
    fails = 0

    # 1. Python / コア依存
    print("1. Python / コア依存パッケージ")
    print(f"{INFO}Python {sys.version.split()[0]}")
    for mod in ("numpy", "pandas", "scipy"):
        try:
            m = __import__(mod)
            print(f"{OK}{mod} {getattr(m, '__version__', '?')}")
        except ImportError:
            print(f"{NG}{mod} が無い → pip install {mod}")
            fails += 1

    # 2. yfinance
    print("\n2. yfinance")
    try:
        import yfinance as yf
        print(f"{OK}yfinance {getattr(yf, '__version__', '?')}")
    except ImportError:
        print(f"{NG}yfinance が無い → pip install yfinance")
        print("    ※ これが無いと実データ・ペーパーテストは一切動きません。")
        return 1

    # 3. 米国セクターETF取得
    print("\n3. 米国セクターETF (XLB, XLF, XLK) の取得")
    try:
        us = yf.download(["XLB", "XLF", "XLK"], period="1mo",
                         auto_adjust=True, progress=False)
        n = len(us["Close"].dropna(how="all"))
        if n > 0:
            print(f"{OK}米国ETF {n} 営業日分を取得")
        else:
            print(f"{NG}米国ETFが空。ネットワーク/プロキシを確認")
            fails += 1
    except Exception as e:
        print(f"{NG}米国ETF取得に失敗: {e}")
        fails += 1

    # 4. 日本個別株取得
    print("\n4. 日本個別株 (7203.T トヨタ, 6758.T ソニー) の取得")
    try:
        jp = yf.download(["7203.T", "6758.T"], period="1mo",
                         auto_adjust=True, progress=False)
        has_open = "Open" in jp.columns.get_level_values(0)
        n = len(jp["Close"].dropna(how="all"))
        if n > 0 and has_open:
            print(f"{OK}日本株 {n} 営業日分を取得 (始値→終値リターン計算に必要なOpen列あり)")
        else:
            print(f"{NG}日本株データが不完全 (Open列={has_open}, 日数={n})")
            fails += 1
    except Exception as e:
        print(f"{NG}日本株取得に失敗: {e}")
        fails += 1

    # 5. 戦略パイプライン end-to-end (合成データで予測→ウェイトが通るか)
    print("\n5. 戦略パイプライン (予測→正規化ウェイト)")
    try:
        import numpy as np
        from src.config import JP_LARGE_CAP, StrategyConfig
        from src.data import make_synthetic_equity_data
        from src.backtest import to_weights
        from src.signal import predict_next_day_jp_detailed

        cfg = StrategyConfig()
        d = make_synthetic_equity_data(list(JP_LARGE_CAP.keys()), n_days=200)
        us_v, jp_v = d.us_cc.values, d.jp_oc.values
        Wn = cfg.window
        t = len(d.dates) - 2
        pred, f_hat, _ = predict_next_day_jp_detailed(
            us_v[t - Wn:t], jp_v[t - Wn + 1:t + 1], us_v[t],
            lam=cfg.lam, k=cfg.n_factors)
        w = to_weights(pred, cfg)
        gross = float(np.abs(w).sum())
        net = float(w.sum())
        assert np.isfinite(pred).all() and abs(gross - 1.0) < 1e-6 and abs(net) < 1e-9
        print(f"{OK}予測 shape={pred.shape}, グロス={gross:.3f}, ネット={net:+.1e} (ドルニュートラル)")
    except Exception as e:
        print(f"{NG}パイプライン実行に失敗: {e}")
        fails += 1

    print("\n" + "=" * 50)
    if fails == 0:
        print("✅ 全チェック合格 — UM790でペーパーテスト運用が可能です。")
        print("   次: python scripts/run_japan_equity_forward.py --source yfinance")
        return 0
    print(f"❌ {fails} 件の問題があります。上記 [NG] を解消してください。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
