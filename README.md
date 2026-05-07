# e07fullscan

E07乳剤フルスキャン解析ツールキット。

## セットアップ

```bash
# 解析ライブラリのみ
pip install -e .

# Webビューアも使う場合
pip install -e ".[server]"

# 開発環境（テスト・lint含む）
pip install -e ".[dev]"
```

依存ライブラリ: numpy, scipy, opencv-python, matplotlib, PyYAML  
Webビューア追加依存: flask

## パッケージ構成

```
e07fullscan/
├── io/
│   └── image_reader.py   # SPNG形式リーダー
├── server/               # Webビューア（要 flask）
│   ├── app.py
│   └── __main__.py
├── tracking/             # 飛跡追跡（開発中）
└── utils/                # 共通ユーティリティ（開発中）
```

## SPNGフォーマット

E07フルスキャンで使われる独自フォーマット。ビュー（視野）ごとにJSONとSPNGファイルがペアで存在する。

- **JSONファイル**: メタデータ（画像サイズ・枚数・各スライスのXYZ座標・アフィン変換係数など）
- **SPNGファイル**: PNGブロブを連結したバイナリコンテナ  
  JSON内の `Images[].Path` が `ファイル名.spng&バイトオフセット&バイト長` の形式で各画像の位置を示す

## SPNG Image Reader

```python
from e07fullscan.io import load_spng

reader = load_spng("path/to/scan.json")
```

### 属性

| 属性 | 型 | 内容 |
|---|---|---|
| `reader.image_type` | `ImageType` | `depth`, `height`, `width` |
| `reader.affine_p2s` | `list[float]` | ピクセル→ステージ座標のアフィン係数（6要素） |
| `reader.datetime` | `str` | 撮影日時文字列 |
| `reader.entries` | `list[ImageEntry]` | 各スライスのSPNG内位置とXYZ座標 |

### 画像の読み込み

```python
len(reader)              # スライス枚数
reader.z_positions()     # 各スライスのZ座標 (ndarray, float64)

img   = reader.read(0)         # グレースケール画像 (H×W, uint8)
raw   = reader.read_raw(0)     # 生PNGバイト列（デコードなし）
stack = reader.read_stack()    # 全スライスをスタック (N×H×W, uint8)

reader[0]       # read() と同等
for img in reader:  # イテレーション対応
    ...
```

## Webビューア

SPNGデータをブラウザで閲覧し、処理パイプラインをインタラクティブに操作できる。

### 起動

```bash
python -m e07fullscan.server /path/to/data/root

# ホスト・ポートを指定する場合
python -m e07fullscan.server /path/to/data/root 0.0.0.0 8080
```

KEKCCで動かしてローカルから見る場合はSSHトンネルを使う：

```bash
ssh -L 8000:localhost:8000 username@login.kekcc.jp
```

ブラウザで `http://localhost:8000` にアクセス。

### 操作

| 操作 | 動作 |
|---|---|
| サイドバーでJSONをクリック | zスタックを読み込む |
| マウスホイール / 左右矢印キー | Zスライスを切り替え |
| VIEW: FIT/ACTUAL | 全体表示 ↔ 等倍表示 |
| 等倍表示でドラッグ | パン |

### 処理パイプライン

サイドバーのチェックボックスで各ステップを個別にon/offできる。有効なステップが順番に適用される。

| # | ステップ | 処理 | 主なパラメータ |
|---|---|---|---|
| 1 | **Fog Removal** | GaussianBlurとsubtractによるFog除去 | ksize=31 |
| 2 | **Threshold** | 二値化 | thresh=19 |
| 3 | **Noise Removal** | 面積・コンパクト度による輪郭フィルタリング | area<5, compactness<15 |
| 4 | **Hough Lines** | HoughLinesPによる飛跡の緑線オーバーレイ | minLineLength=15, maxLineGap=8 |

## テスト

```bash
pytest
```
