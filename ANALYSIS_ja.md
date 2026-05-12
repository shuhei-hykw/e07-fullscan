# E07 フルスキャン — 解析ノート（日本語版）

時系列の開発日誌。結果だけでなく議論・仮説・行き詰まりの記録も含む。
技術的な API リファレンス: README.md（英語）。
英語版: ANALYSIS.md

**開始:** 2026-05-08

---

## リファレンス

### スキャン形状

| 項目 | 値 |
|---|---|
| プレート | MOD108 / PL12 / tohoku-v1 / AREA00 |
| ビュー数 | 2025（45 × 45 グリッド）|
| FOV 間隔 | ~0.5 mm |
| FOV サイズ | ~594 × 594 μm |
| **ピクセルスケール** | **0.29 μm/px**（スキャナ JSON は 3.0 → 誤り）|
| 乳剤深さ | ~150 μm |
| スライス数 | ~100、z 間隔 ~1.5 μm/スライス |

0.29 μm/px の確認：2048 px × 0.29 = 594 μm ≈ 0.5 mm FOV 間隔。

### パイプライン

```
SPNG 画像
    │  [スライス・ビューごと]
    ▼  Z 投影 → フォグ除去 → Otsu 二値化 → ノイズ除去
    │  HoughLinesP
    ▼  トラックセグメント（chunk_NNNN.parquet、計 ~24M トラック）
    │  品質指標: length_px, mean_intens, angle_deg, n_grains, grain_density
    ▼  全ペア交点計算 + エンドポイント確認
    │  スライスごとの vertex 候補（vertices.parquet）
    ▼  z スライス間の XY 近傍マージ
    マージ済み vertex 候補（vertices_merged.parquet）
```

### 物理目標

**現フェーズ**: 任意の反応 vertex の efficiency 優先選択。
対象: ビーム反応、単一 Λ 超核、α 崩壊チェーン、核星。

**最終目標**: ダブル超核（ΛΛ）探索。
シグネチャ：同一ビュー内で ~100–500 μm（30–167 px）離れた 2 つの connected vertices：
1. **プライマリ vertex** — ビーム + 標的 → ΛΛ超核 + 他粒子
2. **セカンダリ vertex** — 超核の弱崩壊（kink または小さな星）

**重要方針：efficiency 最優先（purity は後回し）**
specials_x20 はすべてダブル超核イベントであり、ほかにも多数の vertex が存在する。
ダブル超核 vertex を loss しないことが最重要課題。

### ビーム方向

ビームは乳剤面の X 方向（画像の水平方向）に進む。
全トラックの 22% は `angle_deg < 15°` または `> 165°`（ビーム方向）。
`beam_angle_cut = 15°` でこれらを除去。

---

## 開発ログ

---

## 2026-05-08 — 初回トラック解析・ピクセルスケール修正

- 2025 ビュー全体に `e07analyze` を実行 → `results/merged.parquet`（~24M トラック）
- スキャナ JSON のピクセルスケール誤りを発見：JSON では 3.0 μm/px だがスキャン形状から **0.29 μm/px** が正しい。`config/default.yaml` の `px_scale_um` を修正。
- 影響：既存 parquet の `grain_density` は 10 倍過小評価。再解析まで `n_grains` を直接使用。

**Hough パラメータ調整（目視確認）：**

| パラメータ | 旧値 | 新値 | 理由 |
|---|---|---|---|
| `hough_thr` | 20 | 35 | ノイズトラック削減 |
| `hough_ml` | 25 px | 50 px | 25 px = 7.3 μm；短すぎてノイズが多い |
| `hough_mg` | 4 | 5 | 僅かな改善 |
| `grain_radius` | 10 px | 15 px | 0.29 μm/px でのグレイン関連付け改善 |

**v1 vertex ラン（初回）：**
- パラメータ: `min_len=100, min_intens=12, max_ep=100`、ビームカットなし
- 結果: **95,160 生 → 8,468 マージ**
- 観察: 保守的すぎ；α トラック（~86 px < 100 px）を miss。

---

## 2026-05-09 — Vertex finding v2; パラメータ緩和

- パラメータ緩和（efficiency 優先方針）：
  - `min_len_px`: 100 → **50 px**（α トラック ~86 px を捕捉）
  - `min_intens`: 12 → **10.0**
  - `max_ep`: 100 → **150 px**
  - `beam_angle_cut`: 0 → **15°**
- v2 結果: **6,976,451 生 → 642,558 マージ** → 爆発。

**v2 爆発の根本原因：**
`max_ep=150` に相対カットなし。50 px の通過トラックの最近エンドポイント ≈ 25 px < 150 px → パスしてしまう。

**修正 — 相対エンドポイントカット（`max_ep_frac`）：**
- 絶対カット: `ep < max_ep`（150 px）
- 相対カット: `ep < max_ep_frac × トラック長`（0.5）

真の vertex トラック: エンドポイント ≈ 0 px → 常にパス。
通過トラック: エンドポイント ≈ 長さ/2 → 相対カットで除去。

- v3 結果（`max_ep_frac=0.5` 追加）: **1,754,298 生 → 221,278 マージ** ✓

---

## 2026-05-10 — 目視確認; 角度広がりフィルタ; 実行トレーサビリティ; v4 ラン

### 目視確認とティーチャーデータ

`scripts/crop_vertices.py` を構築：**RAW** | **フォグ除去** | **二値** の 3 パネル。

v3 から 30 枚のクロップを目視確認（`n_tracks 5–12, n_slices ≥ 20, seed=7`）：

| カテゴリ | 件数 |
|---|---|
| 乳剤アーチファクト（クラック・ブロブ） | 7 |
| 良好なティーチャー（実粒子トラック） | 23 |
| **反応 vertex 候補** | **5** |

**重要知見**: `n_slices` が高くても本物の vertex とは限らない。
乳剤クラックは全スライスに渡って持続 → `n_slices` は純度の保証にならない。

**イベント種別：**
- ✓ **真の反応 vertex** — 多方向に細いトラックが放射状に出る。n_tracks ≈ 8+ で安定。
- △ **トラック交差**（偽陽性・軽微）— `max_ep_frac` で主に抑制済み。
- ✗ **乳剤アーチファクト偽**（偽陽性・主要）— 大きなクラックの端を Hough が検出 → 平行線の密集 → 小さな角度広がりの偽高多重度 vertex。

### 角度広がりフィルタ

`find_vertices()` に `min_angle_spread` を実装。
倍角トリック（[0°,180°) の方向を exp(2iθ) にマップ）で円統計的広がりを計算。

- アーチファクト vertex（n=34）: `angle_spread = 14.8°` → 閾値 ≥ 20° で除去。
- 真の反応 vertex: 広がりが大きい（多方向にトラック）。
- KEKCC ラン: `--min-angle-spread 20.0` を設定。

### v4 vertex ラン（min_angle_spread=20°）

KEKCC アレイジョブ 74625453 — 135 ジョブ完了。
出力: `results/vertices_merged_v4.parquet`（207,259 vertex）。

---

## 2026-05-10 — specials_x20 ティーチャーイベント; 統合テスト

### specials_x20 ティーチャーイベント

確認済みダブル超核（候補）イベント 13 件を
`/gpfs/group/had/sks/Users/shuhei/work/specials_x20/` に提供：

```
D005, D013, IBUKI, IRRAWADY, KISO, MINO, NAGARA,
T004, T004_3body, T004_center, T011, T011_100, T011_200
```

形式: PNG ファイル群 (`0000.png`, ...) + `image.json`。
ピクセルスケール: 0.289 μm/px（フルスキャンと同一）。
z 間隔: ~3 μm/スライス（フルスキャンの 2 倍）。

**パイプライン結果（全スライス、min_angle_spread=0）：**

| イベント | トラック数 | ベスト n | spread |
|---|---|---|---|
| IBUKI | 39,563 | 10 | 31.9° |
| NAGARA | 61,711 | 9 | 23.2° |
| MINO | 39,858 | 18 | 30.2° |
| KISO | 38,256 | 11 | 42.4° |
| IRRAWADY | 33,943 | 10 | 38.7° |
| D005 | 97,737 | 13 | 35.5° |
| D013 | 91,253 | 12 | **13.4°** |
| T004 | 141,982 | 10 | **18.0°** |
| T011 | 26,202 | 10 | **8.2°** |

D013, T004, T011 の spread < 20°: v4 フィルタでプライマリ vertex が除去される。
統合テストでは `min_angle_spread=0` を使用（フィルタ最適化は別問題）。

### 統合テストスイート（`tests/test_specials.py`）

`@pytest.mark.slow` テスト 2 種：
1. `test_special_reader_loads` — 全 13 イベント、スライス読み込み確認
2. `test_special_vertex_detected` — パイプライン全実行、`n_tracks_max >= 5` を確認

`pytest -m slow` で実行。デフォルト pytest では skip。

---

## 2026-05-11 — vertex 候補マップ; グラウンドトゥルース戦略; インデント修正

### vertex 候補マップ生成

IBUKI, D013, T004, T011 の全候補オーバーレイマップを生成
（`results/specials_crops/*_all_vertices_map.png`）。

**重要な発見（致命的）**: パイプラインが見つける最高 n の vertex 候補は
すべて **2 本のトラックの交差点** であり、真の反応 vertex ではなかった。
T011 のみ dist_center=50px で "かなり近い" 候補があった。

### グラウンドトゥルース収集戦略

`scripts/click_vertex.py` を作成：
- 全スライスの min projection を表示
- ユーザーが反応 vertex をクリック → ピクセル座標を記録
- ディレクトリ指定で自動 min projection

### コード品質: インデントルール修正

CLAUDE.md 規定の 2 スペースインデントに 13 ファイルを修正。

---

## 2026-05-12 — グラウンドトゥルースクリックセッション

`scripts/click_vertex.py` で 9 イベントの真の反応 vertex 位置を記録。

**重要な知見**: 全 specials イベントの真の vertex は
- XY: 画像中心付近（(1024,1024) から 72 px 以内）
- Z: ≈ 0 μm（スキャン z 範囲の中央）

`tests/specials_gt.json` に記録（XY ピクセル座標 + z_um + z_slice）。
許容範囲: 200 px XY、30 μm Z。

| イベント | 真の vertex | n_clicks |
|---|---|---|
| D005 | (1020, 1023) z=0.4μm | 1 |
| D013 | (998, 990) z=0.0μm | 1 |
| IBUKI | (982, 968) z=0.2μm | 2 |
| IRRAWADY | (1010, 1018) z=-0.3μm | 3 |
| KISO | (1096, 1028) z=-0.2μm | 3 |
| MINO | (1016, 1018) z=0.0μm | 2 |
| NAGARA | (1020, 1021) z=-0.1μm | 3 |
| T004 | (1023, 1038) z=0.4μm | 1 |
| T011 | (992, 984) z=-0.1μm | 2 |

`test_special_vertex_position` を追加：
merged vertex が ground truth の 200 px XY + 30 μm Z 以内にあるか確認。
当初はほぼ全イベントで失敗（pipeline がクロッシングを選ぶ問題）。

---

## 2026-05-13 — KDTree クラスタリング修正; パイプライン status スクリプト

### 根本原因の特定: グリッドハッシュクラスタリングのバグ

旧実装の問題点：
intersection 点を `eps_px=25px` のグリッドセルにハッシュするだけだったため、
グリッドセル境界にかかった 2 点が 24px しか離れていなくても
別クラスタに入ってしまっていた。

星型 vertex の n 本のトラックから n(n-1)/2 個の intersection が生まれても、
25px のセルをまたいで分散すると各クラスタの n_tracks が 2–3 にしかならず
`min_tracks=3` フィルタで落ちていた。

**修正**: `cKDTree.query_pairs()` + union-find（経路圧縮）に置き換え。
eps_px 以内のすべての intersection 点が必ず同じクラスタに入るようになった。

**検証結果**: production cuts のまま、全 9 specials イベントで
ground truth 200 px XY + 30 μm Z 以内に n_tracks_max ≥ 5 の merged vertex を検出：

| イベント | n | dist XY | dist Z |
|---|---|---|---|
| T011 | 8 | **2px** | 0.0μm |
| D005 | 12 | 6px | 0.0μm |
| NAGARA | 6 | 8px | 0.0μm |
| MINO | 10 | 22px | 0.0μm |
| D013 | 9 | 129px | 0.1μm |
| IBUKI | 9 | 138px | 0.0μm |
| T004 | 11 | 149px | 0.3μm |
| IRRAWADY | 7 | 160px | 0.0μm |
| KISO | 9 | 170px | 0.1μm |

### パイプライン status スクリプト

`scripts/status.py` を追加（引数なし）：
```
python scripts/status.py
```
トラック chunk 進捗・vertex マージ状態・KEKCC ジョブ状況を
1 コマンドで確認可能。

---

## 未解決課題 / 次のステップ

- [ ] **`pytest -m slow` 全 35 テスト通過確認**（`test_special_vertex_position` を含む）
- [ ] **2D 解析への移行検討**: Z 投影（±2〜4 スライス）+ コントラスト改善（CLAHE）
      で個別スライス解析に変更する案を議論済み。現行手法は保持しつつ試験的に実装。
- [ ] **前処理修正**: `noise_amax_upper` を `preprocess()` に追加；
      KEKCC での `e07analyze` 再実行が必要。
- [ ] **ティーチャーデータ拡充**: 30 クロップ中 5 件の反応 vertex 候補は少ない；
      `vertices_merged_v4.parquet` から 100–200 クロップを目視確認。
- [ ] **トラック再解析**: `px_scale=0.29` で `e07analyze` を再実行
      （`grain_density` が現在 10 倍過小評価）。
- [ ] **2 頂点探索**: 同一ビュー内 30–167 px 離れた vertex ペア探索 → ΛΛ トポロジー。
- [ ] **grain density による PID**: 修正後は α / 遅いプロトン / MIP の識別に使用可能。
