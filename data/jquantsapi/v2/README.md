# ⚠️ 合成サンプルデータ（実データではありません）

このディレクトリの parquet は `scripts/make_sample_data.py` が生成した**ダミーデータ**です。
ノートブック `notebooks/oc_strategy_analysis.ipynb` を端から端まで動かして挙動を確認するためのもので、
**投資判断・戦略評価には使えません**（値動きは乱数＋弱い平均回帰で人工的に作っています）。

実運用・本番分析では、J-Quants API で取得した本物のデータで同名ファイルを**上書き**してください。

## ファイルとスキーマ
| ファイル | 列 |
|---|---|
| `stock_prices_mod.parquet` | `Date, Code, O, H, L, C, V, AdjC, TurnoverValue` |
| `stock_list_mod.parquet` | `Code, CompanyName, Mrgn` |
| `margin_alert.parquet` | `Date, Code, RestrictedByJSF`（発生=`"1"`/解除=`"0"` の疎なレコード） |

## 再生成
```bash
python scripts/make_sample_data.py
```
