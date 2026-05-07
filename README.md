# e07fullscan

E07 emulsion full-scan analysis toolkit.

## Setup

```bash
# 解析ライブラリのみ
pip install -e .

# Webビューアも使う場合
pip install -e ".[server]"

# 開発環境（テスト・lintを含む）
pip install -e ".[dev]"
```

## Package Structure

```
e07fullscan/
├── io/         # Data I/O
│   └── image_reader.py   # SPNG形式の読み込み
├── server/     # Webビューア (Flask)
│   ├── app.py            # Flaskアプリ本体
│   └── __main__.py       # CLIエントリポイント
├── tracking/   # 飛跡追跡（準備中）
└── utils/      # 共通ユーティリティ（準備中）
```

## SPNG Image Reader

E07フルスキャンで使われるSPNG形式（JSON + バイナリコンテナ）を読み込む。

```python
from e07fullscan.io import load_spng

reader = load_spng("path/to/scan.json")

print(len(reader))           # z枚数
print(reader.image_type)     # ImageType(depth=8, height=2048, width=2048)
print(reader.z_positions())  # 各スライスのZ座標 [mm]

img = reader.read(0)         # numpy array (H×W, uint8)
stack = reader.read_stack()  # numpy array (N×H×W, uint8)

for img in reader:           # イテレーション対応
    ...
```

### SPNG Format

- **JSONファイル**: メタデータ（ImageType、各画像のXYZ座標など）
- **SPNGファイル**: PNGブロブを連結したバイナリコンテナ
- JSON内の `Images[].Path` フィールドが `filename.spng&offset&length` の形式でSPNGファイル内の位置を示す

## Web Viewer

SPNGデータをブラウザで閲覧し、処理パイプラインをインタラクティブに操作できる。

### 起動

```bash
python -m e07fullscan.server /path/to/data/root
# ホスト・ポートを指定する場合
python -m e07fullscan.server /path/to/data/root 0.0.0.0 8080
```

KKECCで動かしてローカルから見る場合はSSHトンネルを使う：

```bash
ssh -L 8000:localhost:8000 username@login.kekcc.jp
```

ブラウザで `http://localhost:8000` にアクセス。

### 操作方法

- サイドバー: ディレクトリを辿り、JSONファイルをクリックするとzスタックを読み込む
- マウスホイール / 左右矢印キー: Zスライスを切り替え
- **VIEW: FIT/ACTUAL**: 全体表示 ↔ 等倍表示（等倍時はドラッグでパン）

### 処理パイプライン

サイドバーのチェックボックスで各ステップを個別にon/off可能。

| # | ステップ | 処理内容 |
|---|---|---|
| 1 | **Fog Removal** | GaussianBlur(31×31) → subtract によるFog除去 |
| 2 | **Threshold** | 二値化（閾値19） |
| 3 | **Noise Removal** | 面積・コンパクト度による輪郭フィルタリング |
| 4 | **Hough Lines** | HoughLinesP による飛跡の緑線オーバーレイ |

## Tests

```bash
pytest
```
