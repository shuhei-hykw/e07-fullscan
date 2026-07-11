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

- [x] **グラウンドトゥルース記録**: `tests/specials_gt.json` 完成（2026-05-12）
- [x] **vertex miss の根本原因**: グリッドハッシュクラスタリングバグ → KDTree union-find で修正（2026-05-13）。全 9 イベントが position test をパス。
- [x] **v5 vertex ラン（KEKCC）**: 完了（2026-05-13）。n_tracks≥10 が +83.5%。
- [x] **2 頂点探索**: `find_vertex_pairs()` 実装（2026-05-13）。p_ntracks≥10 で 5,059 候補。
- [ ] **ΛΛ 候補の目視確認**: vertex_pairs_v5 上位候補の 2 頂点 crop を生成してスキャン。
- [ ] **2D 解析の試験実装**: ±2〜4 スライス重ね合わせ + コントラスト改善（CLAHE）。
- [ ] **前処理修正**: `noise_amax_upper` を `preprocess()` に追加；KEKCC 再実行が必要。
- [ ] **ティーチャーデータ拡充**: 更新された vertex 結果から 100–200 クロップを目視確認。
- [ ] **トラック再解析**: `px_scale=0.29` で `e07analyze` を再実行（`grain_density` 修正）。
- [ ] **grain density による PID**: 修正後は α / 遅いプロトン / MIP の識別に使用可能。

---

## 2026-05-13 — v5 全スキャン vertex ラン・ΛΛ vertex ペア探索

### v5 KEKCC ラン（KDTree 修正適用）

135 チャンク全てを KDTree union-find 修正済みコードで再実行。
パラメータは v4 と同一。

| 指標 | v4 | v5 | 変化 |
|------|----|----|------|
| マージ済み vertex（min_slices=2） | 207,259 | 212,777 | +2.7% |
| n_tracks_max ≥ 5 | 102,178 | 114,089 | +11.7% |
| n_tracks_max ≥ 10 | 2,143 | 3,933 | **+83.5%** |

高多重度 vertex の大幅増加がバグ修正の効果を実証。
vertex マップ：`results/vertex_map_v5.png`。

### Z 単位の確認

`z_mean` カラムの値は **mm 単位**（スキャナステージ座標）。
- z_step ≈ 0.003 mm = 3 μm/スライス
- 全スキャン z 範囲：−0.259〜−0.048 mm（≈ 211 μm 乳剤厚）

これにより vertex ペア探索の dz フィルタは 0.010 mm (10 μm) が適切。

### ΛΛ トポロジー vertex ペア探索

`find_vertex_pairs()` と `scripts/find_pairs.py` を実装。

探索条件：
- 同一ビュー内
- XY 距離：30–167 px（90–500 μm）
- Primary：n_tracks_max ≥ min_n_primary
- Secondary：n_tracks_max ≥ 3、n_slices ≥ 2
- dz < 0.010 mm（同一乳剤深さ）

v5 での結果（min_n_primary=5）：

| n_primary カット | ペア数 | ビュー数 |
|-----------------|-------|---------|
| ≥ 5 | 95,353 | 2,025 |
| ≥ 8 | 14,760 | 1,901 |
| ≥ 10 | 5,059 | 1,153 |
| ≥ 15 | 1,423 | 250 |

p_ntracks ≥ 10 で 5,059 候補は半自動スキャンが可能な規模。
次ステップ：上位候補の 2 頂点クロップ画像を生成して目視確認。

### ゴールデン ΛΛ 候補選択

多段階物理フィルタ:
1. XY 距離: 90–500 μm
2. Primary: n_tracks_max 10–20
3. Secondary: n_tracks_max 3–8 (ΛΛ 弱崩壊星と矛盾しない)
4. 連結トラック存在 (tol=20 px)
5. スコア = `p_ntracks × s_ntracks / log(1 + dist_px)`

結果: **1,220 ゴールデン候補、709 ビュー** (`results/vertex_pairs_v5_golden.parquet`)
- 399 ビュー: 候補が 1 つだけ（最高優先度）
- 202 ビュー: 候補が 2 つ

上位候補プロファイル: p_ntracks≈16-20, s_ntracks≈6-8, dist≈150-400 μm。
次のステップ: 上位 200 クロップを目視確認して ΛΛ トポロジーを同定。

## 2026-05-13 — 角度広がりの頂点ペア出力への伝播

### angle_spreadカラムの伝播

`merge_vertex_slices()`関数はすでに`angle_spread_best`と`angle_spread_max`を
マージ済み頂点DataFrameに保持していた（本日earlier追加）。しかし
`find_vertex_pairs()`がこれらをペア出力に渡していなかった。修正：各ペアレコードに
`p_angle_spread`と`s_angle_spread`（`angle_spread_best`を使用）を伝播するよう変更。

パイプラインをエンドツーエンドで再実行：
1. `find_pairs.py` → angle_spreadカラム付き73,751ペア
2. `filter_pairs_by_track.py`（tol=20 px）→ 25,842フィルタ済みペア
3. Golden選択 → 1,220ペア（以前と同数、spread情報付き）

### goldencandidatesのangle_spread統計

全頂点は生産カット（min_angle_spread=20°）を通過済みなので全値≥20°。分布：

| 頂点 | 平均 | 中央値 | 25パーセンタイル | 75パーセンタイル |
|------|------|--------|-----------------|-----------------|
| Primary   | 31.8° | 32.4° | 26.7° | 37.1° |
| Secondary | 29.3° | 28.9° | 24.2° | 34.0° |

Secondary頂点はPrimaryより若干低いspread（プロング数3–8 vs 10–20と整合）。
両分布は大きく重なっており、angle_spread単独では明確な識別子にならない。

goldencandidates中の低spread割合：
- p_angle_spread < 25°: 18.4%（225/1220）
- s_angle_spread < 25°: 29.4%（359/1220）
- 両方 < 25°: 5.4%（66/1220）

両方が25°以下の頂点はゴーストである可能性があり、精査が必要。

### クロップ画像再生成

`crop_pairs.py`を更新し、n_tracksラベルの横に`sp=XX°`を表示するよう変更。
Top-200 goldenクロップを`results/pair_crops_v5_golden/`に再生成（angle_spreadラベル付き）。

**未解決問題**：
- [ ] angle_spreadとs_ntracksの組み合わせでより良い背景除去ができるか？
- [ ] 両方低spread（66ペア）は本当にゴーストか、それとも整列崩壊幾何の実事象か？

### クロップ画像のCLAHEコントラスト強調

`crop_pairs.py`でアノテーション前にCLAHE（clipLimit=2.0, tileGridSize=8×8）を適用。
z投影画像に適用してトラックと頂点構造が目視確認しやすいよう局所コントラストを強調。

rank-1候補への効果: raw平均=183 → CLAHE平均=160（コントラスト拡張）。
200枚のgoldenクロップを`results/pair_crops_v5_golden/`にCLAHE付きで再生成済み。

### noise_amax_upper: 前処理での大型アーティファクト除去

`e07fullscan/tracking/_finder.py`の`preprocess()`に`noise_amax_upper`パラメータを追加。
0より大きい値を設定すると、Houghライン検出前に面積>閾値のバイナリblob を除去する。

目的：大型銀粒子クラスタ、乳剤fold、宇宙線ミューオン残留トラックを除去。
デフォルト=0（後方互換のため無効）。YAMLで設定可能：`noise_amax_upper: N`。

KENKCCでの`e07analyze`再実行が必要（将来のタスク）。

### Teacher dataの拡充

v5マージ済み頂点からteacher crop 200枚を生成（n_tracks≥8, n_slices≥4）、
`results/vertex_crops_teacher_v5/`に保存。既存60枚と合計260枚のteacher dataset。

## 2026-05-13 — ピクセルスケール修正・v6パイプライン・KISO specials調査

### 重大バグ: ピクセルスケールが10倍誤っていた

`_vertex.py` 内の定数 `PX_SCALE = 3.0` μm/px は10倍誤り。正しい値はスキャナJSON
（`AffineP2S = [0.00028889, ...]`）とスキャン形状（2048 px × 0.29 = 594 μm ≈ 0.5 mm
FOV間隔）から確認された **0.29 μm/px**。

影響: 旧v5ペア探索は d=30–167 px ≈ 9–48 μm でΛΛ事象の期待値（90–500 μm）と
比べてスケールが1桁小さかった。v5の全"golden"候補は誤ったスケールに基づいていた。

修正: `_PX_SCALE_UM = 0.29`, `_D_MIN_PX = 310`（90 μm）, `_D_MAX_PX = 1724`
（500 μm）を `e07fullscan/clustering/_vertex.py` に設定。

### v6パイプライン（修正済みスケールで再実行）

| ファイル | 件数 | 備考 |
|---|---|---|
| `vertex_pairs_v6.parquet` | 1,200,346 | 全ペア d=90–500 μm |
| `vertex_pairs_v6_prefilter.parquet` | 43,013 | p:10–20, s:3–8 |
| `vertex_pairs_v6_filtered.parquet` | 97 | 接続トラックフィルタ tol=30 px |

接続トラックフィルタ（P→S区間にHoughトラックを要求）は97ペアを出力したが、
すべて荷電粒子の重トラック（単一トラックが停止・散乱）。ΛΛトポロジーではなく
重粒子を選んでしまう。根本原因: Houghセグメントの99.5%が310 px未満
（z-slice 1枚≈3 μmなので1枚当たりのトラック長は50–100 px程度）。
接続トラックフィルタは**v6で廃止**し、手法を再検討する。

### 座標系の同定

KISO specials（NLAB-PC06）とfullscan（NLAB-PC13）のステージ座標を比較し、
fullscanのピクセル→ステージ変換として以下が正しいことを確認：

```
stage_x = view_cx - (px_x - 1024) × 0.00029 mm   (x軸反転)
stage_y = view_cy + (px_y - 1024) × 0.00029 mm   (y軸同方向)
```

検証: V00001173（ビュー中心 1.499, 13.001）にKISOを当てはめると:
- 一次頂点 期待ステージ(1.748, 12.882) → ピクセル(95, 617)
- 二次頂点 期待ステージ(1.668, 13.048) → ピクセル(441, 1186)
  （最近傍検出済み頂点: (432,1241) n=6, 56 px離れ ≈ 16 μm）
- P-S距離: 666 px = 193 μm → **KISOの既知距離193 μmと完全一致** ✓

### KISOスペシャルのマッチング結果

KISOは fullscanプレート範囲内にステージ座標が収まる**唯一の**スペシャル事象
（1.748, 12.882 mm）。他の specials（D005, D013, IBUKI等）は異なる顕微鏡で
取得されており、較正データなしでは座標変換ができない。

V00001173 でのKISO対応状況:
- **一次頂点(95, 617)**: z-sliceごとに6–9本のHoughライン検出（hough_ml=25では
  長さ25–50 px）。本番閾値 hough_ml=50 ではこれらが最短ライン長未満で
  **頂点検出されない**。原因: 乳剤表面近傍（z ≈ −0.076 mm, 上位2–3 slice）で
  急傾斜トラックのz断面投影が短い。
- **二次頂点(432, 1241) n=6 sp=24.8**: 検出済み・頂点カタログに収録。
  KISO二次期待位置から 56 px ≈ 16 μm。

**KISOはv6_prefilterペアに含まれていない** — 一次頂点が未検出のため。
二次頂点はv6ペアに含まれるが、他の無関係な一次と対になっているだけ。

一次頂点ミスの根本原因: `hough_min_line = 50 px`（14.5 μm）。乳剤表面付近では
3-μm z-sliceでのトラック投影長が25–40 px（傾斜角 > 11°）になり得る。
`hough_min_line` を25–30 px に下げれば検出できるはず。

副作用リスク: 短いライン閾値はノイズヒットを増やす → n_tracks/angle_spread
分布への影響を慎重にベンチマークする必要あり。

### アクション項目

- [ ] `hough_min_line`を30 pxに下げ、確認済みspecials近傍ビューで頂点再検出テスト
- [ ] KISO以外のspecialsの座標オフセット同定（較正データまたは共通特徴による）
- [ ] 接続トラックフィルタの再設計: 一次→二次方向の粒子密度カット、
      または一次頂点での方向孤立性カット
- [ ] 高傾斜角トラック対応: ライン交差ベースの頂点探索器の追加検討

---

## 2026-05-13 — クロスビュー頂点ペア探索；KISO 復元

### 発見：KISO primary がビュー境界をまたぐ

KISO イベントの予測位置：primary 段階座標 (1.769, 12.883)、secondary (1.668, 13.048)。
フルスキャンの view 配置では：

| View | Center (mm) | KISO primary px | KISO secondary px |
|---|---|---|---|
| V00001173 | (1.499, 13.001) | (93, 617) — 左端付近 | (441, 1186) → 検出 (432, 1241) |
| V00001174 | (2.000, 13.001) | (1821, 617) — 右端付近 | (2169, 1186) — 範囲外 |

V00001173 では primary が px_x=93 (2048 px 幅の view の左端から 93 px)。
左方向のトラックが view 境界で切断されるため、hough_ml=50 では n≤5 しか検出されない。
V00001174 では hough_ml=30 を使うと (1854,630) n=5 sp=35.6 が期待位置から 37 px に検出。

**結論：KISO は V00001173/V00001174 の境界にまたがる cross-view イベント。**
単一 view 内の頂点ペア探索では復元できない。

### クロスビューペア探索：`scripts/find_crossview_pairs.py`

新スクリプトを実装：
1. Convention C で各頂点の stage 座標 (mm) を計算
2. stage 座標で cKDTree を構築
3. 各 primary 候補（n ≥ min_n_primary）について、**異なる view** の頂点を d_min–d_max mm 範囲で探索
4. Z 方向分離カット (max_dz_mm; デフォルト 0.200 mm)

重要な変更点：cross-view では物理 primary が view 境界で弱く見えるため
「primary の n ≥ secondary の n」制約を削除。
また max_dz_mm を 0.010 mm (intra-view) から 0.200 mm に緩和
（KISO の primary-secondary dz = 70.2 μm、dip angle ~21° に対応）。

### KISO cross-view 検出結果

v5 カタログ (hough_ml=50) での結果：

```
P=(432,1241) n=6 sp=24.8  V00001173  (物理的 secondary、高 n)
S=(1888,716) n=5 sp=23.5  V00001174  (物理的 primary、切断)
dist = 171.5 μm  (期待 193 μm、誤差 11%)
dz   = 70.2 μm   (dip angle ~21° と整合)
```

**KISO は cross-view ペアとして復元された。** ただし役割が逆転
（物理 secondary の方が n が大きく「P」として出力）。距離誤差 22 μm は
頂点位置誤差（primary ~35 μm + secondary ~16 μm）から生じる。

hough_ml=30 使用時、V00001174 の primary 候補は (1854,630) n=5 sp=35.6 に改善
→ cross-view 距離 = **198.0 μm**（期待 193 μm、誤差 2.6%）

### 設定変更：hough_ml 50 → 30

`config/default.yaml` を更新：`hough_ml: 30`（0.29 μm/px で 8.7 μm）。
表面頂点や view 境界 primary の短いトラックセグメント検出が改善する。
全パイプライン（2025 view × 58 スライス）の KEKCC 再実行が必要。

### クロスビューの背景とスケール

v5 カタログに対して min_n=5/3、d=90–500 μm、max_dz=200 μm で実行すると
18,822,640 cross-view ペア。系統的背景が観測される：
(px≈430,1240) と adjacent view の (px≈1890,720) のペアが多くの view 行で繰り返す
（d≈165–177 μm）。これは view 境界をまたぐ重粒子トラック（ビーム粒子等）が
両側に偽の star-vertex を作るため。
抑制策：max(n_p,n_s)≥10 かつ min(n_p,n_s)≥6 かつ両 sp≥30° → ~67,717 ペア。

### アクションアイテム（更新）

- [x] hough_min_line を 30 px に変更（config/default.yaml 更新済み）
- [ ] KEKCC で hough_ml=30 にてパイプライン全再実行
- [ ] v6 カタログで `find_crossview_pairs.py` を実行して cross-view ΛΛ ペアを探索
- [ ] 非 KISO specials の座標オフセット決定
- [ ] cross-view ペアの背景抑制（n, sp カット）開発
- [ ] KISO 検証比較画像（specials vs フルスキャン crop）実装

---

## 2026-05-14 — n順序バグ修正；全9 specials 検出；cross-view フィルタ研究

### バグ修正: `find_vertex_pairs` n順序制約の削除

`e07fullscan/clustering/_vertex.py` の `find_vertex_pairs` 関数から
`if nt[pi] < nt[si]: continue` を削除した。

**背景:** 元々の意図は「一次頂点は二次頂点より多いトラック数を持つ」を強制することで、
物理的には Ξ⁻ 停止星が Λ崩壊より多くのプロングを持つことに基づいていた。
**なぜ間違っていたか:** 視野境界 (KISO) や多体崩壊では、二次頂点が切断された一次頂点より
多くのトラックを持つことがある。制約の削除は安全。ロールラベル（一次/二次）は
相対順序ではなくトポロジー（n_tracks 閾値）で定義。

**影響:** v7 ペアを正しい距離範囲 (90-500 μm) で再生成: **1,479,220 intra-view ペア**
(v6: 1,200,346 から +23%、P.n<S.n ペアがアンブロックされたため)。

### Specials パイプラインテスト: 全9イベント検出

全9つの confirmed specials_x20 イベントに対してフルパイプライン実行。
全イベントで候補ペアが生成された。

| イベント | 頂点数 | n_max | ペア数 | 備考 |
|---------|-------|-------|-------|------|
| D005 | 358 | 15 | 48,887 | — |
| D013 | 331 | 15 | 27,367 | — |
| IBUKI | 281 | 14 | 24,170 | — |
| IRRAWADY | 158 | 11 | 4,828 | — |
| KISO | 192 | 11 | 9,491 | 真のペア発見 |
| MINO | 304 | 19 | 33,562 | — |
| NAGARA | 221 | 9 | 12,236 | — |
| T004 | 380 | 14 | 47,555 | — |
| T011 | 135 | 14 | 3,919 | — |

**KISO 真のペアが specials 画像で回復:**
```
P=(1108,1090) n=6 nsl=4  z=-0.225 mm   (gt一次から 62 px)
S=(751,1589)  n=9 nsl=13 z=-0.211 mm   (gt二次から 11 px)
dist = 178 μm   (期待 194 μm、誤差 8%)
dz   = 0.014 mm
```
n順序修正前はこのペアがブロックされていた (P.n=6 < S.n=9)。

**課題:** 各 specials 画像で 4,000-50,000 ペアが生成される。
真のペアはバックグラウンドに埋もれており、ランキングが必要。

### フルスキャン: KISO のみが現在の走査範囲内

頂点カタログ (`vertices_merged_v5.parquet`) は x=[−0.001, 22.001] mm,
y=[0.002, 22.000] mm の 22×22 mm² エリアをカバー。9 specials 中
**KISO のみ**がこのエリア内 (view_x=1.75, view_y=12.88 mm)。
他の8つは走査境界から 58 mm 以上離れている。

KISO はフルスキャン cross-view ペアカタログで確認:
```
P = V00001173 (354,1204) n=11 nsl=7 sp=42.3°
S = V00001174 (1888,716) n=5  nsl=6 sp=23.5°
dist = 152 μm  (期待 194 μm、誤差 22%)
dz   = 0.026 mm
```
22% の距離誤差は v5 カタログが hough_ml=50 で構築されたため。
hough_ml=30 での再実行により改善が期待される。

### Cross-view ペアバックグラウンド抑制

18.8M cross-view ペアに段階的カットを適用:

| カット | ペア数 | KISO |
|-------|-------|------|
| 全件 | 18,822,640 | 132 |
| 隣接ビューのみ | 14,800,258 | 132 |
| + p_ntracks 6-20, p_sp≥30° | 4,208,859 | 48 |
| + s_ntracks≥4, s_sp≥20° | 3,326,423 | 48 |
| + dist 90-250 μm, dz≤0.030 mm | 211,692 | 8 |
| + p_nslices≥5, s_nslices≥4 | **109,376** | **7** |

KISO は全カットを生き残る。7つの KISO 候補は真のペアと6つのバックグラウンドを含む。
真のペアは p_ntracks×p_angle_spread の組み合わせが最大。

### v5 ペア: 致命的エラー (誤った距離範囲)

`vertex_pairs_v5.parquet` が d_min=30 px (8.7 μm)、d_max=167 px (48 μm)
(hough_ml の値を誤って使用) で生成されていたことを発見。v5 ペアは ΛΛ 解析に使えない。
v6・v7 が正しい 90-500 μm 範囲を使用。

### Intra-view 接続ペア: v6_filtered

`filter_pairs_by_track.py` を v6 ペアに適用: 1.2M から **97 ペア**が生存。
p_ntracks 10-19、p_sp 20-45°、dist 90-307 μm。KISO は含まれない (cross-view)。
この 97 ペアが視覚検査の最優先候補。

### アクション項目 (更新)

- [x] `find_vertex_pairs` の n順序制約を修正 (2026-05-14)
- [x] n順序修正で v7 intra-view ペアを再生成
- [x] 修正後に KISO が specials 画像で検出されることを確認
- [x] v5 距離範囲バグを文書化
- [x] Cross-view フィルタ研究: 18.8M → 109K (KISO 生存)
- [ ] KEKCC で hough_ml=30 によりフルパイプライン再実行
- [ ] v6 カタログで find_crossview_pairs.py を実行
- [ ] Cross-view ペアに接続トラックフィルタを適用
- [ ] 97 intra-view 接続ペアの視覚検査
- [ ] 非 KISO specials の座標オフセット決定

### v7_filtered: 接続トラックフィルタの結果

`filter_pairs_by_track.py` を v7 (min_n_primary=10、90-500μm) に適用:

```
v7_filtered:  540 ペア  (min_n_primary=10, tol=50px)
  ΛΛ範囲 (p_n:6-20, s_n:3-15, sp>=20):  398 ペア (368 ユニーク)
    ─ v6_filtered と共通:  97 ペア  ← 全 v6 候補が回収された ✓
    ─ n順序修正で新規:    301 ペア
  強候補 (p_sp>=30, s_sp>=25, p_n>=8, s_n>=4):  120 ユニークペア
```

v6_filtered の97ペアが全て v7_filtered に含まれる: n順序修正は既存の
候補を失わずに、新たに301ペアを追加した。

**次のステップ:** 120 強候補の視覚的検査 (crop_pairs.py) で真の ΛΛ
事象と重核相互作用バックグラウンドを区別する。

## 2026-05-14 — 接続トラックアノテーションと Tier A 候補選定

### 接続トラックプロパティのアノテーション

`scripts/annotate_pairs.py`（許容値50px）で123件の強候補全てにアノテーションを付与:

- `conn_mean_intens`: 接続トラックの平均強度
- `conn_grain_density`: 接続トラックの粒子密度
- `conn_angle_diff`: トラック方向とP→S軸との角度差
- `conn_len_ratio`: トラック長 / dist_px

主要な知見:
- `conn_angle_diff` ≈ 0° (全候補でほぼ0° — 弁別子として使えない)
- `conn_mean_intens`: 平均16.8、std=6.1。35以上は2件のみ
  (rank2: 37.1, rank11: 39.8)
- 視覚的偽陽性(rank1,4,5)のintensは普通(25.5, 13.9, 12.4) —
  重粒子トラックが複数の短セグメントに分割されるため、
  接続トラック強度単独では重粒子フォールスポジティブを識別できない

### Tier A / B / C 分類

| Tier | 基準 | 件数 |
|------|------|------|
| A | s_n≥8, p_sp≥30°, s_sp≥28°, d=90-400μm, I<38 | 25 |
| B | s_n≥6, p_sp≥28°, s_sp≥25°, d=90-500μm | 53 |
| C | 残り | 45 |

Tier A は既知specials(s_n=9-13, 両sp>25°)に最も近いパラメータ範囲。
hough_ml=50切り捨てによりトラック数が低めなのでs_n≥8を使用。

出力ファイル:
- `results/vertex_pairs_v7_strong_ann.parquet`: 123件(接続トラック情報付き)
- `results/vertex_pairs_v7_tier_a.parquet`: 25件のTier A候補
- `results/pair_crops_v7_ann/`: 123枚アノテーション付きPNG (I=印字済み)
- `results/pair_crops_v7_tier_a/`: 25枚のTier A優先検査用クロップ

### 次のステップ
1. `pair_crops_v7_tier_a/` の25枚を視覚検査
2. cross-viewペア(109,376件)への接続トラックフィルター適用
   (Ξ⁻トラックがビュー境界をまたぐ: primaryは右端に、secondaryは左端から)
3. KEKCC hough_ml=30での再実行（全スキャン対応）

## 2026-05-14 — クロスビュー接続トラックフィルター（filter_xview_pairs.py）

### 方法

`scripts/filter_xview_pairs.py` がビュー境界通過トラックを確認:
- **Primary view**: P頂点から60px以内の端点を持ち、もう一方の端点が
  secondary方向のビュー端（300px以内）に近いトラック
- **Secondary view**: S頂点から60px以内の端点を持ち、もう一方の端点が
  primary方向のビュー端（300px以内）に近いトラック

VX/VYインデックス差からビュー端方向を決定:
高VX ↔ 高stage_x ↔ 低pixel_x (Convention C)

### 結果

| 段階 | 件数 |
|------|------|
| 事前カット後 | 29,408 |
| 境界通過フィルター後 | 2,986 |
| ΛΛ範囲（p_n≤20, s_n≤15）後 | 2,952 |
| 強候補（s_n≥5, p_sp≥30°, s_sp≥22°, d≤230μm）| 1,596 |

KISO真ペア（P=(354,1204) n=11 sp=42° → S=(1888,716) n=5 sp=23°,
d=152μm, dz=0.026mm）は全段階を通過 ✓（ΛΛ-range内順位: 988/2952）

出力ファイル:
- `results/vertex_pairs_xview_v1_conn.parquet`: 2,986件
- `results/vertex_pairs_xview_v1_conn_ll.parquet`: 2,952件 ΛΛ範囲
- `results/vertex_pairs_xview_v1_strong.parquet`: 1,596件 強候補

---

## 2026-05-14 — v6パイプライン：イントラビュー・クロスビューペア探索

### 背景

v6トラッキングはhough_ml=30（正しい値、v5のhough_ml=50は誤り）を使用し、
70.8Mトラック（v5の24Mの3倍）を生成。頂点統合により237,029頂点（+11%）。

### イントラビューペア（vertex_pairs_v6）

実行結果：**1,851,442ペア**（v7の1,479,220より+25%）。
次ステップ：接続トラックフィルター適用（v7パイプラインと同様）。

### クロスビューペア（vertex_pairs_xview_v6）

- 生成：23,474,643ペア（90–500μm、dz≤0.200mm）
- v1と同じ事前フィルター適用後：2,219,749ペア（v1の109,376の20倍）
  - 要因不明：primary1件あたりの候補数がv6では72.1、v1では4.7
- 境界通過フィルターへの適用が困難なため、追加の絞り込みを実施：
  - p_sp≥35°、p_n≥8、d≤400μmで**204,405ペア**に削減
  - KISOは通過（p_sp=42°>35°、p_n=11>8、d=152μm<400μm）
- 境界通過フィルター実行中（2026-05-14時点）

生成ファイル：
- `results/vertex_pairs_xview_v6.parquet`: 23,474,643件
- `results/vertex_pairs_xview_v6_filtered.parquet`: 2,219,749件
- `results/vertex_pairs_xview_v6_prefiltered.parquet`: 204,405件
- `results/vertex_pairs_xview_v6_conn.parquet`: 実行中

---

## 2026-05-14 — 並行エージェント用の共有議論ログ

Claude Code も同じリポジトリで実行中のため、`discussion.md` を追記専用の
共有調整ログとして導入した。目的は、作業中の仮定、編集中のファイル、
未解決の論点を見える形にしつつ、`ANALYSIS.md` と `ANALYSIS_ja.md` の
時系列日誌形式を維持することである。

Codex から Claude への初回メモでは、作業ツリーが既に dirty であることを
確認し、v6 クロスビュー候補数の過剰増加について、低い Hough 最小長の影響、
隣接ビュー判定、座標/インデックス規約のどれが主因かを論点として提示した。
また、スクリプト変更前に意図する出力ファイル名を記録し、中間生成物の上書きを
避ける運用を提案した。

---

## 2026-05-14 — 日本語版 discussion log の追加

ユーザーの依頼を受けて、`discussion.md` に対応する日本語版として
`discussion_ja.md` を作成した。内容は Codex から Claude への初回調整
メッセージを日本語で反映し、現在の作業内容、仮定、編集中ファイル、
予定している出力ファイル名を追記するよう依頼している。

README の調整ルールも更新し、英語版 `discussion.md` と日本語版
`discussion_ja.md` の両方を明記した。これにより、英語の簡潔な
エージェント間ハンドオフを残しつつ、日本語メモをリポジトリ指示に沿った
専用の場所で管理できる。

---

## 2026-05-14 — discussion 監視ルールを agent ルールへ追加

ユーザーから、discussion log の監視ルールを `AGENTS.md` と `CLAUDE.md` に
反映するよう依頼があった。両ファイルに Agent Coordination セクションを
追加し、リポジトリ作業前、共有ファイル編集前、最終報告前に
`discussion.md` と `discussion_ja.md` の両方を確認することを必須化した。

このルールでは、両 discussion log を追記専用として扱い、ジョブ実行、
出力生成、スクリプト変更の前に、入力、出力、生成ディレクトリ、担当ファイルを
記録するよう定めた。README も更新し、この運用が必須ルールになったことを
明記した。

---

## 2026-05-14 — 方針転換：単体頂点検出へ

これまでのパイプラインは ΛΛ Primary/Secondary ペアの探索に特化していた。
ユーザーの指示により、ペア位相構造の要件を廃止し、個々の反応頂点を
直接検出する方向に転換した（原子核星、α崩壊、single Λ、ΛΛ primaryなど、
乳剤中に可視化されるあらゆる頂点トポロジーが対象）。

動機：ペア位相構造は特定のシグナルモデルを前提とし、それ以外の頂点を
検出できない。直接的な頂点カタログを作ることで、乳剤イベントのより
完全な全体像が得られる。

### マージ済み頂点への品質カット

`results/vertices_merged_v6.parquet`（237,029件）に以下のカットを適用：

| カット | 値 |
|-------|-----|
| n_tracks_max | ≥ 8 |
| angle_spread_best | ≥ 28° |
| n_slices | ≥ 4 |

出力：`results/vertices_quality_v6.parquet` — **10,750件**。

### クロップ生成

n_tracks_max 降順で上位500候補の画像クロップを生成。
出力ディレクトリ：`results/vertex_crops_v6/`（PNG 500枚）。

カバー範囲：n_tracks_max = 82 → 15、全45×45ビュー領域にわたる。

ファイル命名規則：
```
NNN_V{view_id}_L0_VX{vx}_VY{vy}_..._n{ntracks}_sl{nslices}_z0_x{px}_y{py}.png
```

次ステップ：500枚のクロップを目視確認し、バックグラウンドの混入状況を
評価するとともに、詳細測定候補の頂点を特定する。

---

## 2026-05-27 10:28 JST — ランキング変更: n_tracks_max → sp×nsl; 目視検査

### Dead end: n_tracks_max ランキング

`n_tracks_max` だけで並べると逆効果だった。
top-500（`vertex_crops_v6/`）はビームパイルアップや重粒子フェイクに
支配されていた（n_tracks_max: 82→15）。
KISOの最近傍候補（n=8, sp=36°, nsl=9）はtop-500に含まれていなかった。

### 新ランキング: score = angle_spread_best × n_slices

Codex/Claude合同議論（2026-05-14 21:56 JST）を経て、
`score = angle_spread_best × n_slices` を採用した。理由:
- 多方向への広がり（真の多プロング星型トポロジー）を評価する
- z方向での再現性（単層アーチファクトでない）を評価する
- 高トラック多重度を直接報酬せず、重粒子バイアスを回避する

新クロップセット: `results/vertex_crops_v6_sp_nsl/`（500枚）。
コマンド: `crop_vertices.py --sort-by sp_nsl --n-samples 500`。

### 目視検査結果（2026-05-27）

ユーザーが500枚全てを確認。旧n_tracks_maxランキングから**劇的に改善**:

- 反応点らしい画像（多プロング星型）が大幅に増加
- 残存バックグラウンドは2種類:
  1. **大きなゴミ・グリッドポイント**: 乳剤アーチファクトまたは
     スキャナグリッドが誤って頂点として検出されたもの
  2. **無関係な交差飛跡**: 無関係な2本の飛跡が交差しているだけで、
     物理的な反応点ではないもの

**結論**: sp×nsl を今後のランキングスコアとして正式採用。

### 次のステップ

- ゴミ・交差飛跡バックグラウンドを追加カット
  （例: 2本の最大離角、等方性指標）で抑制できるか検討する
- 目視検査結果からラベル付きカタログを生成する
- `specials_x20/` は `../specials_x20` へのシンボリックリンク（9事象の
  確認済みスペシャルイベントの外部参照画像データ、読み取り専用、
  パイプライン生成物ではない — 2026-05-27 discussion にて解決済み）

---

## 2026-05-27 21:31 JST — 博士論文に基づくranking review

ユーザーが関連する博士論文 `S.H.Hayakawa_D.pdf` を追加した。Codexは現在の
vertex preprocessing議論に関係するChapter 4とChapter 5を確認した。

重要な解釈: 論文中のevent categorizationは、単一のstar-like scoreではなく、
topologyとtrack contextを組み合わせている。具体的にはincoming trackが
distortedかstraightか、charged-particle emissionがあるか、beam trackが
vertexに見えるかを使っている。Hypernuclear productionは `sigma-stop`、
つまりendpoint近傍で乱れたstopping negative trackとcharged-particle
emissionとして分類されており、単なる高multiplicity starではない。

これは現在のrecall-first preprocessing方針を支持する。Hough-based featureは
広いimage retrievalには有用だが、物理的に重要なendpoint contextをまだ持って
いない。高い `n_tracks_max`、高い `n_slices`、見た目に強いnuclear starを
唯一のrankingで支配的にすると、KISOのような既知ハイパー核事象を落とす
危険がある。

次のalgorithmic direction: broad reaction-like、hypernuclear-recall、
background-rich reserveの複数preprocessing channelを維持する。その上で、
candidate vertices、track endpoints、track-segment edges、incoming-trackの
straightness/distortion、outgoing prongs、beam-track evidence、nearby secondary
verticesを含むgraph/topology表現へ進む。

---

## 2026-05-28 — スコア式の定量化; 2チャンネルranking決定

2026-05-27に提案したscore代替案を、fullscan plate range内にある唯一の
special（KISO）に対して定量化し、recall-first preprocessing段の
ranking scoreを決定した。議論: discussion_ja.md 2026-05-28 15:48–17:01 JST。

### 各scoreでのKISO rank（vertices_quality_v6、N=10,750）

KISO anchor = V00001173内の最近傍マッチ（sp=41.4°、nsl=7、n=9）。

| Score              | KISO rank   | パーセンタイル | top-500必要条件 |
|--------------------|-------------|------------|---------------|
| `sp` のみ          | **798**     | 7.4%       | nsl≥4         |
| `sp × sqrt(nsl)`   | 4,475       | 41.6%      | nsl≥12        |
| `sp × log(nsl)`    | 4,227       | 39.3%      | nsl≥11        |
| `sp × min(nsl,10)` | 5,947       | 55.3%      | nsl≥10        |
| `sp × nsl`（従来）  | 6,188       | 57.6%      | nsl≥14        |

### 重要な発見: nslのcap/減衰はKISOを救済しない

傾いていた `sp × min(nsl,10)` はほぼ効かない（rank 5,947 対 6,188）。
KISOのnsl=7はcap値10を*下回る*ためmin(7,10)=7で恩恵ゼロ；capはnsl>10の
頂点（全体の35%）をdampするだけ。nslを掛けるscoreはすべて、z深さ方向に
中程度しか広がらない真の局所反応頂点にペナルティを与える。rankingから
nslを外す（`sp`のみ）場合のみ、KISOが使えるcandidate budget（top-800）に
入る。

nslを外しても浅いartefactでlistは埋まらない: sp≥41.4°のpool（816頂点）は
n_slicesが健全に分散（4-7: 24%、8-10: 33%、11-13: 24%、≥14: 19%）し、
n_tracks_max≥17は4%のみ（nsl≥4のquality floorが既に適用済みのため）。

### 2リスト診断（persistence biasの可視化）

- `hough_recall_sp`    = `sp` でrank、nsl≥4はfloorのみ
- `hough_broad_sp_nsl` = `sp × nsl` でrank（従来の唯一ranking）

top-N重複: 500→15%、1000→23%、2000→36%。top-500の構成:

| feature           | recall_sp | broad_sp_nsl |
|-------------------|-----------|--------------|
| sp 中央値          | 43.2      | 38.2         |
| nsl 中央値         | 10        | 18           |
| nsl ≥14           | 19%       | **100%**     |
| n_tracks_max ≥17  | **4%**    | **14%**      |

`broad_sp_nsl` top-500はnsl≥14で完全飽和し、n≥17のbackground-rich層を14%
含む；`recall_sp`はnsl分布がバランス良く、重粒子star混入もはるかに少ない。

### 決定: 両者を別々のranked viewとして維持（置換ではない）

Codex/Claude共同合意（discussion 17:01 JST）:

- **`hough_recall_sp`** — `sp`主導、nsl≥4はfloorのみ、n≥17はbackground
  flag → このrecall-first段の**hypernuclear-recallルート**。nsl乗数は
  （弱いものでも）加えない。nslこそここで避けたいbiasの源だから。
- **`hough_broad_sp_nsl`** — 従来の `sp × nsl` ranking。broad
  reaction-like / 重い核star のサーベイ用に維持。

これにより2026-05-27の結論（「sp×nslを今後のranking scoreとして確認」）は
*broad* channelのみに**限定**され、唯一のrankingではなくなる。
（過去のdiary entryはlab-notebook方針に従いそのまま残す。）

### 次のステップ

- 新規の大規模crop生成より先に、step-5（noise-removal）互換性artifact:
  fullscan 1 view + KISO + T011（最小のlow-sp special）を
  `e07fullscan/tracking/_finder.py::preprocess()` に通し、post-noiseの
  前景率、connected-componentの面積分位、matched projectionを比較。
  解釈は保守的に ― raw輝度の不一致だけでspecials_x20を失格にしない。
- low-sp specials（T011/T004/D013）: graph-branch判断の前に、clicked GT
  頂点周辺でbounded Hough failure-mode diagnostic（4カテゴリ）。

---

## 2026-05-28 — Step-5 互換性チェック: specials_x20 vs fullscan-image

specials_x20 を conventional Hough branch の sanity-check anchor として使える
かを、両ソースを*同じ step-5 preprocessing 後*（Hough/graph 分岐前の共有境界）
で比較して検証した。2026-05-28 の scope lock に従い、**visual-review server は
使わず、batch の `e07fullscan.tracking._finder.preprocess()` を直接呼んだ**ので、
統計は batch パイプラインが見るものと完全一致（noise_amax_upper=0）。スクリプト:
`scripts/step5_compat.py`、出力: `results/step5_compat/`。

ソース: fullscan view V00001173（KISO カタログマッチを含む）、KISO、T011
（最小の low-sp special）。各々で find_tracks の中心スライス ±4 平均投影を
preprocess() に通した。

| metric                 | fullscan V00001173 | KISO        | T011         |
|------------------------|--------------------|-------------|--------------|
| shape / dtype          | 2048² uint8        | same        | same         |
| n_slices               | 58                 | 60          | 50           |
| dz (µm/slice)          | 3.00               | 3.00        | 3.00         |
| px scale (µm)          | 0.29 (config)      | 0.289       | 0.289        |
| raw proj mean / std    | 182.5 / 39.3       | 98.0 / 54.7 | 145.6 / 19.8 |
| post-step5 前景率      | 7.27%              | 6.64%       | 4.17%        |
| CC count               | 2548               | 1353        | 1532         |
| CC area 中央値 (px²)   | 62                 | 125         | 55           |

### 所見

- **幾何はソース間で完全一致**（2048² uint8、3.0 µm/slice、0.289 µm/px）。
  （注: fullscan view JSON は identity AffineP2S を持ち、物理スケールは config
  の 0.29 µm/px に由来。）
- **生輝度は大きく異なる**（取得時の露光/コントラスト、NLAB-PC13 vs PC06）―
  ただし保守的には、これだけで specials_x20 を参照データとして失格にしない。
- **step-5 後に表現が収束**: 前景率はすべて 4〜7% 帯に収まり、connected-
  component の count/area も同オーダー、トラック様構造が3ソースすべてで視覚的に
  生存（montage.png）。正規化機序は fog removal（GaussianBlur − img）に続く
  画像ごとの Otsu で、閾値が適応し生輝度差を吸収する。

### 結論

specials_x20 は*同じ step-5 preprocessing 後*なら conventional Hough branch の
sanity-check anchor として利用可能。定性/sanity 用途では step-5 を超える正規化
は不要。expert への未解決質問: NLAB-PC06 vs PC13 の光学/照明/カメラ等価性 ―
だが主な懸念（生輝度）は step-5 が吸収する。

### dormant な重複についての注記（debris チューニング前に修正）

コードレビュー（discussion 2026-05-28）で、`server/app.py` が
`_process()`/`_collect_stats()` で fog/Otsu/noise を再実装し、
`tracking.preprocess()` にある **`noise_amax_upper` 分岐を欠く**ことが判明。
`noise_amax_upper = 0` のため現状は無害だが、大型ブロブ除去を有効化した瞬間に
viewer が batch より under-clean になる。branch-neutral な preprocessing
モジュールを抽出し tracking と server の両方が呼ぶことで合意（Codex/Claude）。
これは scoring/compatibility と混ぜず、behavior-preserving な別タスク
（旧/新の回帰テスト付き）として実施する。

### 次のステップ

- low-sp specials（T011/T004/D013）: clicked GT 頂点周辺での bounded Hough
  failure-mode diagnostic（preprocessing でトラック消失 / Hough 線抽出失敗 /
  頂点マージ失敗 / 頂点はあるが scalar score 低）。

---

## 2026-05-28 — low-sp specials failure-mode diagnostic

3つの low-sp 確認事象（T011/T004/D013）について、clicked GT 頂点で
conventional Hough branch を段階的にウォークし、低い angle spread が
preprocessing/抽出/association の失敗か、それとも真のトポロジー限界かを判定
した。batch 関数を直接呼出、設計は Codex と合意（discussion 2026-05-28
19:04/19:11）。スクリプト: `scripts/lowsp_diag.py`、crops:
`results/lowsp_diag/`。find_tracks は v6 config（hough_ml=30）、find_vertices
既定（min_angle_spread=0）、±12 スライスでマージ、2半径（200/300px）。

| event | fg@R200 | endpts/body in R200 | near-GT spread R200/R300 | single vtx | merged vtx (±12) |
|-------|---------|---------------------|--------------------------|------------|------------------|
| T011  | 6.4%    | 38 / 38             | 32.4° / 31.6°            | d=3px n=5 sp=16.7 | d=10px n=10 nsl=8 sp=12.7 |
| T004  | 6.0%    | 17 / 17             | 22.6° / 34.0°            | d=2px n=6 sp=2.5  | d=11px n=10 nsl=10 sp=8.2 |
| D013  | 7.4%    | 48 / 48             | 29.8° / 29.0°            | d=14px n=13 sp=31.8 | d=9px n=13 nsl=12 sp=31.8 |

### 所見

- **3つとも cat 1/2/3 の hard failure はない。** 構造は preprocessing を生存
  （GT で fg 6–7%）、Hough 線は GT で端点サポート付きに抽出
  （endpoints_in == body_in → through-going でない；min_body 0.4–7.5px）、
  頂点も tolerance 内に形成（2–14px）。low-sp 問題は spread/scoring 段で
  あって、画像/Hough/association 存在の段ではない。

- **D013 は実際には low-sp でない。** GT 頂点はきれいに検出（sp=31.8°、
  n=13、nsl=12）、sp-recall で問題なく上位。旧「D013 sp=13.4°」
  （2026-05-10）は*別の* best-n 頂点を測ったもので、真の GT 頂点ではない。
  D013 は low-sp 問題集合から外れる。

- **T011 は断片化/under-association の artifact。** crop は GT に明確な
  多飛跡星を示し、近傍の端点サポート付き線は 32° に広がるが、検出頂点 sp は
  12.7° のみ。25px clustering（eps_px）+ endpoint cut が真の星をより共線な
  sub-vertex に分割している。diversity は画像に存在するが scalar 頂点 sp が
  取りこぼす。Hough branch 内で回収可能とみられる。

- **T004 は真性な low-sp core。** 直近頂点 sp=2.5°（single）/8.2°（merged）、
  near-GT spread は R200 で 22.6°、R300 で 34° に広がる ― 共線に近い core に
  大きな半径で prong（forward-boosted トポロジー）。本当の graph-branch
  candidate。

### 含意

low-sp specials の recall 懸念は、大半が測定/断片化の artifact（T011, D013）
であって、Hough 表現の根本的限界ではない。graph branch が明確に要るのは
T004 のみ。

### 次のステップ

- Hough-branch テスト（graph 着手前）: 頂点 angle_spread をより広い
  endpoint-association 半径で再計算する、または scoring 前に GT tolerance
  程度で隣接 sub-vertex をマージし、T011 が 32° の near-GT spread に向けて
  回収する一方 T004 は低いままか確認。T011 が回収するなら sp-recall ranking
  が graph branch なしで拾える。

---

## 2026-05-29 — T011 spread-recovery テスト: 断片化を確認

2026-05-28 の low-sp diagnostic で提案した Hough-branch 修正を検証: T011 の
低い頂点 spread は clustering-fragmentation の artifact か? GT スライスで GT
に最も近い検出頂点をアンカーとし、endpoint-association 半径 R を掃引、最近傍
端点が R 内のトラックで angle_spread を再計算。スクリプト:
`scripts/lowsp_spread_radius.py`、プロット
`results/lowsp_diag/spread_vs_radius.png`。batch 関数を直接呼出。

| event | 検出 sp | R=25 | R=50 | R=75 | R=100 | R=150 | R=200 |
|-------|---------|------|------|------|-------|-------|-------|
| T011  | 16.7    | 28.5 | 34.3 | 34.6 | 32.5  | 33.1  | 32.4  |
| T004  | 2.5     | 3.1  | 3.7  | 5.6  | 21.5  | 24.2  | 22.6  |
| D013  | 31.8    | 29.2 | 27.2 | 31.7 | 32.3  | 33.1  | 30.1  |

### 所見

- **T011: 断片化 artifact、完全に回収可能。** R=25 で 28.5°、R=50 で ~34°
  に達する（検出 scalar sp は 12.7–16.7°）。真の多飛跡星は頂点直上にあり、
  25px の交点 clustering がそれを共線 sub-vertex に分割した。広い spread
  半径で Hough branch 内で回収できる ― T011 に graph 作業は不要。
- **T004: 真性な共線 core。** R≤75 で 3–6°、R≥100 で遠方トラックを取り込んで
  ようやく ~22° だが sp=28 cut をきれいに超えない。直近頂点は本当に共線
  （forward-boosted）― 真の graph-branch candidate。
- **D013: low-sp でない**（どの半径でも ≥27°）― positive control。

総じて、3つの「low-sp」specials のうち D013 は wrong-vertex の誤ラベル、T011
は広い spread 半径で回収可能、真性 low-sp core は T004 のみ。low-sp 事象の
recall 懸念は大半が測定 artifact。

### 広い spread 半径を採用する前の注意

このテストは広半径 spread が signal を回収する（T011）ことを示すが、コストは
未検証: 全体で広げると crossing-track / background 頂点の spread も上がり、
sp-recall purity を損ないうる。signal 側は検証済み、background 側は採用前に
catalog レベルの確認が必要。

### 次のステップ

- background コストの測定: broad-catalog の n=8–10 頂点サンプルで広半径
  spread を再計算し、sp=28 を超える数を数える。広半径が background spread を
  ひどく膨らませるなら tight 半径を維持。
- T004: graph-branch candidate（Codex 確認 / 他 z での再確認待ち）。

---

## 2026-05-29 — 訂正: T004 の low-sp は algorithmic、物理ラベルは保留

2026-05-28/05-29 の low-sp エントリへの訂正（append-only 方針により上記は
残し、本エントリで限定する）。Codex の指摘（discussion 2026-05-28 22:06）を
受け、T004 を「forward-boosted topology」/ sigma-stop と記述したのは
コードが示す内容を超えていた。

訂正後の立場:

- **事実（コードから）**: T004 の clicked GT 頂点は tolerance 内に検出される
  が angle spread は低いまま（直近 ~2.5°、R≥100 で遠方トラックを取り込んで
  ようやく ~22°）、sp=28 quality cut をきれいに超えない。Hough scalar 表現
  における真性な low-sp core で、T011 の clustering-fragmentation artifact
  とは異なる。algorithmically、3つのうち T004 が graph/topology-branch
  candidate。
- **専門家に保留（コードからでない）**: その low-sp core が物理的に
  sigma-stop / forward-boosted ハイパー核トポロジーかどうかは乳剤物理の
  解釈であり、コード由来の事実ではない。ユーザー / ドメイン専門家への質問
  として flag、断定しない。

---

## 2026-05-29 — 広い spread 半径の background-cost; T004 z-persistence

low-sp scoring スレッドを2つの bounded テストで締めた（batch 関数を直接呼出、
設計は Codex と合意、discussion 2026-05-29 11:06）。

### Background-cost チェック（`scripts/bg_cost_spread.py`）

vertices_merged_v6 から broad-catalog の n_tracks_max 8–10 頂点を 80 サンプル
（seed=7、63 が usable）、アンカー angle_spread を R=25（tight）vs R=50
（T011 回収半径）で再計算、2026-05-29 sweep と同方法。

| metric | R=25 | R=50 |
|--------|------|------|
| spread 中央値 | 29.6 | 32.2 |
| spread p90    | 38.4 | 38.2 |
| Δ(R50−R25) 中央値 / p90 | — | 2.2 / 15.4 |

- 63 のうち 27 が R=25 で sp<28；**そのうち 10 個（37%）が R=50 で ≥28 に昇格**
  （全体の 16%）。高膨張は広半径で膨らんだ near-collinear background
  （sp25 0.4→28.1、1.3→38.1、1.8→27.5）。
- **結論: R=50 のグローバル採用は不可** ― crossing/parallel background を
  カット越えに昇格させる。tight 半径を維持。

global コストなしで T011 を回収できる理由: 真の頂点アンカーで T011 は R=25 で
既に 28.5°。catalog sp が 12.7° だったのは 25px clustering が星をずれた
sub-vertex に分割したから。修正は真の頂点近傍の targeted sub-vertex merge
（tight 半径で回収、background は不変）で、global な半径変更ではない。

### T004 z-persistence

GT（z_slice 100）周辺の slice 92–108 を掃引。GT に最も近い頂点（dist ≤32px）は
全 slice で低 sp（dist ≤18px で sp 2.5–7.4；slice 102 の 14.0 は nearest が
271px 離れているため）。sp~32 の頂点は GT から 100–200px 離れた別構造で GT
頂点ではない。low-sp core は z 近傍全体で持続: **T004 は robust な graph-branch
candidate**（物理ラベルは専門家待ち）。

### scoring スレッドの結論（コード cleanup の前）

1. Hypernuclear-recall ranking = `sp`（nsl 乗数なし；nsl≥4 floor のみ）
   [2026-05-28 決定]。
2. spread-association 半径は tight（R=25）維持；global に広げない。
3. T011 型 fragmentation → targeted sub-vertex merge、cleanup 後の Hough-branch
   実装に先送り（今はやらない）。
4. D013 は low-sp 集合から除外；T004 = graph-branch candidate。

次: コード cleanup（branch-neutral preprocess 抽出 + server dedup + 診断
packaging）、behavior-preserving な別タスクとして旧/新の回帰テスト付きで。

---

## 2026-05-29 — コード cleanup step 1+2: 共有 preprocessing 抽出

Codex と合意した構造 cleanup を開始（discussion 2026-05-28 17:22 /
2026-05-29 14:28）。behavior-preserving；現行 config 下で v6 パイプラインの
解析挙動は不変。

### 変更

- 新規モジュール `e07fullscan/preprocess.py`（branch-neutral、Hough/graph
  分岐前の共有境界）: `fog_remove`、`otsu_binarize`、`remove_noise`（3分岐
  connected-component 面積フィルタの単一ソース）、`preprocess` =
  fog→Otsu→noise。
- `tracking/_finder.py`: ローカル `preprocess` 削除；`e07fullscan.preprocess`
  から import + re-export（`from tracking._finder import preprocess` を使う
  呼び出しは引き続き動く）。intensity 測定用 `fog_img` も `fog_remove` を使い、
  fog 除去の実装を1本化。
- `server/app.py`: `_process`/`_collect_stats` が fog/Otsu/noise を再実装
  しなくなり、共有関数を呼ぶ。これで **dormant な `noise_amax_upper` 欠落を
  解消**（server フィルタは以前 large-blob 分岐を欠いていた）。既定 config
  （`noise_amax_upper=0`）では server 出力は不変；差は large-blob 除去を
  有効化したときのみ ― debris tuning 前に直すと合意した fix。

### 検証

- `tests/test_preprocess.py`（新規）: 新 `preprocess` が旧 `_finder.preprocess`
  の凍結コピーと byte 一致（既定と `noise_amax_upper` 指定）、
  `remove_noise(amax_upper=0)` が旧 server 2分岐フィルタと一致、`amax_upper>0`
  で大型ブロブ除去。4/4 合格。
- `pytest -m "not slow"`: 52 passed、回帰なし。

### 先送り（Codex sequencing）

- Step 3: 再利用可能な診断ヘルパ（tracks_to_df、projection、TRACK_CFG;
  step5_compat/lowsp_diag/lowsp_spread_radius/bg_cost_spread で共通）を
  `e07fullscan/diagnostics/` へ移動し、スクリプトを薄くする。
- Step 4: targeted sub-vertex merge（T011 型の Hough-branch recall fix）。

---

## 2026-05-29 — コード cleanup step 3: 診断 packaging

構造 cleanup を完了。診断スクリプトの behavior-preserving な pure refactor。

### 変更

- 新規 `e07fullscan/diagnostics/` パッケージ（`__init__` + `_common.py`）に、
  4診断スクリプトで重複していたヘルパを集約: `TRACK_CFG`（v6 config）、
  `DF_COLS`、`tracks_to_df`、`projection`、`find_tracks_cfg`。
- step5_compat, lowsp_diag, lowsp_spread_radius, bg_cost_spread を薄型化して
  これらを import；各々固有ロジックのみ保持。
- CLAUDE.md 更新: subpackages に `diagnostics` 追加、`preprocess` を共有
  branch-neutral モジュールとして注記。

### 検証

- `lowsp_spread_radius.py` 再実行で 2026-05-29 記録と数値一致（T011
  R25=28.5/R50=34.3、T004 3.1/3.7、D013 29.2/27.2）― pure refactor。
- `pytest -m "not slow"`: 52 passed。

### 構造 cleanup 完了

- #1 branch-neutral `preprocess` 抽出 ✓
- #2 tracking + server がそれを呼ぶ；dormant `noise_amax_upper` 欠落解消 ✓
- #3 診断 packaging；4スクリプト薄型化 ✓
- #4 targeted sub-vertex merge — 先送りの recall 機能（構造でない）

共有 step-5 境界が batch tracking path と viewer の両方で使う単一実装になり、
診断スクリプトが1ヘルパモジュールを共有。次の解析作業（再開時）: T011 型の
targeted sub-vertex merge（Hough-branch recall fix）。

---

## 2026-05-30 — 整理: dead-code 削除 + パッケージ改名 e07fullscan -> module

構造整理の継続。behavior-preserving；v6 解析挙動は不変。discussion
2026-05-29 20:32 / 2026-05-30 15:31。

### Dead code

- `add_dip_angles`（clustering/_link.py）削除: どこからも呼ばれていない；
  未使用化した `import math` も削除。残存参照なし；テスト green。

### パッケージ改名 e07fullscan -> module

- ユーザー決定（外部から import しないので、generic な import 名でも実用上の
  衝突/検索性コストはない）。
- `git mv e07fullscan module`；全32 .py（package, scripts, tests）、
  pyproject.toml（distribution 名、console entry points 3つ、packages.find）、
  README.md で `e07fullscan` -> `module`。
- CLI コマンド名（e07view/e07analyze/e07merge）は維持、module ターゲットのみ
  変更。top-level run.py は追加せず（スコープ外）。
- 本環境では pip 未インストール（PYTHONPATH 実行）なので再インストール不要；
  他所でインストール済みなら `pip install -e .` で entry points を更新。
- 過去の discussion/ANALYSIS エントリは歴史記録として `e07fullscan` 据え置き。

### 検証

- `pytest -m "not slow"`: 52 passed。
- `lowsp_spread_radius.py` 再実行で 2026-05-29 の数値再現（T011
  R25=28.5/R50=34.3、T004 3.1/3.7、D013 29.2）― 改名は pure。

### 残作業（本整理スレッド）

- legacy ΛΛ-pair コード（find_vertex_pairs + pair scripts 6本）を
  module/clustering/_pairs.py と scripts/legacy/ へ隔離、改名済みツリーで実施。
- crop_vertices の stale オプション（z_target/zpj_mode）: マーク/文書化 or 削除。

---

## 2026-05-30 — 整理: legacy ΛΛ-pair コードの隔離

legacy ΛΛ-pair パス（2026-05-14 に個別頂点検出へ転換して旧化）を隔離し、
active な頂点パスを見やすくした。behavior-preserving。discussion 2026-05-29
20:33。

### 変更

- `find_vertex_pairs`（+ ΛΛ topology 定数）を `clustering/_vertex.py` から
  `clustering/_pairs.py` へ移動。`clustering/__init__.py` は back-compat の
  ため re-export（legacy マークのコメント付き）。_vertex.py は active パス
  （find_vertices, merge_vertex_slices）のみに。
- 6本の ΛΛ-pair scripts（find_pairs, find_crossview_pairs,
  filter_pairs_by_track, filter_xview_pairs, annotate_pairs, crop_pairs）を
  `scripts/legacy/` へ移動、ROOT を修正（`parents[1]` -> `parents[2]`）、
  provenance と実行注記を記した `scripts/legacy/README.md` を追加。`scripts/`
  には active な個別頂点 / 診断 / インフラ scripts のみ残る。

### 検証

- find_vertex_pairs の re-export 同一性 OK；`pytest -m "not slow"` 52 passed；
  legacy scripts は compile し ROOT が repo root に解決。
- Codex 方針により削除しない: pair topology は歴史的結果を生み参照されうる；
  削除はユーザー明示承認後のみ。

### 本整理スレッドの残り

- crop_vertices の stale オプション（z_target/zpj_mode）: マーク/文書化 or 削除。

---

## 2026-05-30 — 整理: crop_vertices の stale オプション削除/マーク

整理スレッドの最終項目。behavior-preserving（crop は引き続き all-slice の
minimum-intensity projection を使用）。

- scripts/crop_vertices.py の未使用内部関数2つを削除: `_load_zproject` と
  `_fog_remove_max`（呼び出しなし；main は `_load_min_projection` を使用）。
  dead な `z_target` ローカルも削除。
- `--zpj-half` / `--zpj-mode` CLI 引数は未使用（`args` から読まれない）。Codex
  方針（user-facing、疑わしければマーク）に従い、CLI back-compat のため残し、
  help を「(unused; crops use all-slice min projection)」とマーク + NOTE
  コメント追加（フラグ削除はしない）。
- compile OK；残存参照なし；sys.path/SpngReader の bootstrap は残った関数に
  存在。

### 整理スレッド完了（Codex 承認待ち）

- dead code 削除（add_dip_angles）；crop stale 関数削除
- パッケージ改名 e07fullscan -> module
- legacy ΛΛ-pair パス隔離（clustering/_pairs.py, scripts/legacy/）
- active 頂点パスと active scripts が見やすくなった
- pytest -m "not slow" green；決定的診断が再現

---

## 2026-05-30 — 構造図 + 解析フロー図

ユーザー要望どおり README とは別の説明図を2つ、Graphviz で作成（整理後の構造を
反映）。Codex が整理を sign-off（discussion 2026-05-30 15:46）し、図が示すべき
5点を指定 — 両方反映。

- `docs/structure.dot` / `docs/structure.png`: ファイル/パッケージ構成。module/
  サブパッケージ（preprocess=共有 step-5、server=viewer をマーク）；scripts/ を
  active / diagnostics / infra / legacy に分類；config と tests を文脈表示。色:
  active 青/緑、viewer オレンジ、legacy グレー破線。
- `docs/analysis_flow.dot` / `docs/analysis_flow.png`: データフロー。raw z-stack
  → 共有 preprocessing（steps 1–5、step-5 境界をラベル）→ conventional
  Hough/vertex branch（find_tracks → find_vertices → merge → quality cut →
  sp / sp×nsl ranking → crops）。viewer は同じ preprocess/find_tracks を呼ぶ
  side client として描画；legacy ΛΛ-pair パスと将来の graph/ML branch は破線。

再生成: `dot -Tpng docs/<name>.dot -o docs/<name>.png`。

---

## 2026-05-30 — Coordination: persistent watcher memory rules

stateless な Codex watcher 実行（`codex exec`, cron, tmux loop）が、一時的な
model memoryではなくrepository filesから安全に文脈を復元できるよう、
`AGENTS.md` を更新した。

- package section を `module`（`e07fullscan` からrename済み）に更新し、現在の
  subpackages と共有 `preprocess` を記載。
- 単純化原則を追加: オッカムの剃刀を優先し、見えるentry pointとfilesを減らす。
  `scripts/` に新しいsubdirectoriesを作らず、diagnostics/legacy codeを日常操作面に
  出さない。
- startup memory rule を追加: 各session/watcherは `AGENTS.md`, `CLAUDE.md`,
  `discussion.md`, `discussion_ja.md`, `ANALYSIS.md`, `ANALYSIS_ja.md` を読む。
- Codex は discussion-main かつ Markdown-only editor、Claude は実装担当である
  ことを再確認。

---

## 2026-05-30 — Tooling: persistent Codex discussion watcher script

ユーザーの明示依頼と、`scripts/` への新規 shell script 追加の例外許可に基づき、
`scripts/codex_discussion_watch.sh` を追加した。

- tmux向けのpersistent loopを実行する。
- 各tickで `codex exec` を呼び、`AGENTS.md`, `CLAUDE.md`, `discussion.md`,
  `discussion_ja.md`, `ANALYSIS.md`, `ANALYSIS_ja.md` から記憶を復元するpromptを
  渡す。
- prompt上で Codex を discussion-main かつ Markdown-only に保つ。
- `flock` で多重実行を避け、`timeout` でCodex実行の詰まりを防ぐ。
- `ROOT`, `CODEX_BIN`, `INTERVAL_SEC`, `TIMEOUT_SEC`, `LOCK_FILE`, `LOG_DIR`,
  `LOG_FILE` を環境変数でoverride可能。

検証: `bash -n scripts/codex_discussion_watch.sh` が成功し、実行権限を付与した。

Follow-up: 初回tmux実行で `codex exec` は `--ask-for-approval` を受け付けない
ことが判明。そのoptionを削除し、`bash -n` を再実行、detached
`codex-discuss-watch` tmux session を再起動し、watcher logで正常なno-op
discussion checkを確認した。

---

## 2026-05-30 — scripts-surface cleanup: run.py + scripts/ 縮小

操作面を再編し、scripts/ の .py/.sh 混在を解消。ユーザー決定: run.py 中心；
scripts/ に新規サブディレクトリを作らない（既存 scripts/legacy/ は維持）。
behavior-preserving。Codex 討議 2026-05-30 17:00–17:45。

### 変更

- 新規 repo-root `run.py`: 単一操作面；サブコマンドが subprocess で既存
  scripts / module entry に委譲（track, view, merge-tracks, vertices,
  merge-vertices, crops, review, map, click, submit-tracking, submit-vertices）。
  run.py に解析ロジックなし。
- 診断を package へ: `module/diagnostics/{step5_compat,lowsp_diag,
  lowsp_spread_radius,bg_cost_spread}.py`、`python -m module.diagnostics.<name>`
  で実行。
- legacy ΛΛ-pair KEKCC shell（kekcc_intra/xconn/filter_job）を scripts/legacy/
  へ移動、参照修正。
- status/monitor を1つに統合: pipeline-overview ロジックを
  `module/pipeline_status.py` へ（run(loop)/main）；`scripts/monitor.py
  --pipeline` が俯瞰（live-job フラグなしの既定）、live-job フラグは旧挙動維持；
  `scripts/status.py` は deprecation wrapper。
- 冗長な submit_kekcc.sh 削除（submit_kekcc.py が bsub をカバー）。
  kekcc_job.sh / analyze.sh の e07fullscan→module 参照漏れ修正。
- scripts/README.md 追加（縮小した surface の地図）。

### end state

scripts/ 現状: README.md、active pipeline CLI（run.py が委譲）、monitor.py
（単一モニタ）、status.py（deprecation wrapper）、LSF shell entry
（kekcc_job.sh, kekcc_vertex.sh, analyze.sh, run_pipeline_v6.sh）、legacy/。
診断は module/diagnostics/ 配下。

### 検証

各 Phase で pytest -m "not slow" 52 passed；monitor.py --pipeline と status.py
wrapper が俯瞰を表示；lowsp_spread_radius（python -m）が 2026-05-29 数値を再現。
コミット: 7f55b9c (run.py), 502ba4d (診断+legacy .sh), ed9377f (status/monitor),
3179e5b (submit_kekcc.sh 削除 + .sh 参照 + README)。

---

## 2026-05-31 — Phase 3: CLI 本体を module/ へ、review パッケージ、Codex sign-off

2026-05-30 の scripts-surface cleanup の続き。薄いラッパー方針を徹底し、
`scripts/*.py` が実ロジックを持たない（各約7行で `module/` へ委譲）形にした。
全工程で挙動は不変。

### なぜ

run.py が dispatcher になった後も重い本体は `scripts/` に残り、パッケージが
実体の真の所在になっていなかった（操作 surface とロジックが2つの木に分裂）。
本体を `module/` へ移すことで `module/` が自己完結し、`scripts/` は純粋な
入口層（ラッパー＋文書化された shell/recipe 入口＋legacy 隔離）になる。

### 変更（family 別、コミット順）

- Family 1 (70733ff): clustering CLI 本体 ->
  `module/clustering/_cli_find_vertices.py`, `_cli_merge_vertices.py`。
- Family 2a (5d47af3): merge_chunks 本体 ->
  `module/merge/_cli_merge_chunks.py`。
- Family 2b (6fe5033): KEKCC submit 本体 ->
  `module/analyze/_cli_submit_kekcc.py`, `_cli_submit_vertex_kekcc.py`。
- Family 3 (e22feb5): 新 `module/review` パッケージ；review CLI 本体 ->
  `_cli_crop_vertices.py`, `_cli_vertex_map.py`, `_cli_review_crops.py`,
  `_cli_click_vertex.py`。
- Family 4 (d3e8fac): live-job monitor 本体 -> `module/utils/job_monitor.py`；
  scripts/monitor.py はラッパーに縮小。（pipeline overview 本体は 2026-05-30 の
  status/monitor 統合で既に `module/pipeline_status.py` に存在。）
- Codex レビュー対応 (edd2dce): CLAUDE.md と AGENTS.md の subpackage 行に
  `module/review` を追加し、`module/pipeline_status.py`（pipeline overview）と
  `module/utils/job_monitor.py`（live-job monitor 本体）を monitor/status
  ヘルパーとして明記。`scripts/status.py --help` を修正し、-h/--help で
  pipeline overview を surprise-run せず deprecation note + docstring を表示し
  exit 0 とした。

### end state

`scripts/` = README.md、薄い Python ラッパー（find_vertices, merge_vertices,
merge_chunks, submit_kekcc, submit_vertex_kekcc, crop_vertices, vertex_map,
review_crops, click_vertex, monitor, status[deprecated]）、文書化された
shell/recipe 入口（analyze.sh, kekcc_job.sh, kekcc_vertex.sh,
run_pipeline_v6.sh）、legacy/。日常操作は run.py、monitor concept は1つ、
重いロジックは `module/` 内。

### 検証と Codex sign-off

pytest -m "not slow" -> 52 passed, 35 deselected（約49s）、clean tree。
Codex は 2026-05-31（edd2dce の後）に最終 structural sign-off を行い、
AGENTS.md/CLAUDE.md が module/ 構造と monitor ヘルパー分離に合致すること、
`scripts/status.py --help` が overview を実行しなくなったこと、run.py/monitor.py
が意図した surface を表示することを確認した。Codex はこの最終確認で full pytest
suite を再実行せず、Claude 報告の `pytest -m "not slow"`（52 passed,
35 deselected）を再実行なしで受け入れた。残り structural blocker なし。README に
run.py を指す簡潔な「Operation Surface」注記を追加し、既存の scripts/*.py 例は
互換パスとして残した（本格的な README 書き直しは Codex 合意で延期）。

---

## 2026-05-31 — close 後の共同レビュー：monitor next-step、legacy docs、2-space

push 後、Codex の再レビューで cleanup に対する follow-up が4件出た。ユーザーは
Claude と Codex が双方納得するまで反復するよう指示。4件すべてを対応し、双方が
sign-off した（discussion 2026-05-31 15:34–18:09）。

### 指摘と修正

1. (挙動) `module/pipeline_status._next_step()` が隔離済み ΛΛ-pair スクリプト
   （find_pairs / find_crossview_pairs / filter_xview_pairs）を指していた。
   ΛΛ-pair は 2026-05-14 に個別頂点検出へ supersede 済みなので、
   `vertices_merged_v6.parquet` 後は "vertices ready: review with run.py
   crops / review / click" を返すよう変更。未使用の pairs/xview/xconn ローカルを
   削除。`scripts/monitor.py --pipeline` で実動作確認。
2. (docs) README「Vertex Pair Search」「Cross-View ΛΛ Pair Search」を
   「(legacy)」表記＋来歴 blockquote にし、コマンドパスを全て `scripts/legacy/`
   へ。物理内容（KISO 結果、v5/v7 注記、出力列）は保持。
   `scripts/run_pipeline_v6.sh` の Step 6-7 も同様に legacy 表記＋
   `scripts/legacy/` パス修正。
3. (docs) README の crop オプション表で `--zpj-half` / `--zpj-mode` を
   「(ignored, back-compat)」とし、`module/review/_cli_crop_vertices.py` の
   コード NOTE と整合。
4. (style) 13ファイルが 4-space で 2-space 規則違反だった。薄いラッパー8個と
   残り5本体（analyze/cli.py, clustering/_link.py,
   diagnostics/{bg_cost_spread,step5_compat,lowsp_spread_radius}.py）を 2-space
   化。5本体は multiline-string 内部を保護する tokenize ベースの halve ＋
   bracket 継続行の visual-indent 整列で変換し、各ファイルを HEAD との
   `ast.dump` 等価でガード。よって挙動保存を証明できる。

加えて README の古い「Package Structure」tree を更新（preprocess.py,
pipeline_status.py, review/, diagnostics/, _cli_* 規約, utils ヘルパーを追加。
compact に保つ）。

### 検証と sign-off

tree 全体 min-indent == 2、odd-indent 0 行（scripts/legacy/ 除く）；
module+scripts 全 `py_compile` OK；diagnostics import smoke OK；
`pytest -m "not slow"` 52 passed, 35 deselected。Codex は独自の最終パス
（git diff --check, py_compile, 5ファイルの AST 等価, legacy grep, 4つの
help/pipeline surface）を実施し、README の wrapper 文を `_cli_*` を超えて
一般化する1点の修正の後、構造・整理に納得と明言。双方 sign-off。

---

## 2026-06-23 — MATLAB グラフ検出器向けエクスポート（試作）

fullscan の出力は `e07/matlab` に置かれたグラフ理論イベント検出器
（`detect_tracks.m` ＋ヘルパー: `detectlseg_smallregion`,
`integrate_smallregions`, `detectbunki`, `mabiki` 他）へ繋ぐ予定。この検出器は
3D ヒット点群から最小全域木＋線分近似で飛跡を構築し、分岐をグループ化する。
Hough パイプラインとは別アプローチ。その stage-1 入力を生成する必要がある。

### インターフェース（ユーザーと決定）

検出器の stage-1 入力はヒット画素リスト `pl = {x, y, z, n, sheet, id}`
（x,y はピクセル、z はスライス番号）。以降の stage は
`dspl = mabiki(pl, 3)` の x,y,z しか使わない。ユーザー決定: `pl` を `.mat` に
直接書出し；ブロック3 の `mabiki` ダウンサンプルは MATLAB 側に任せる；
まず1タイルで試作。

Hough 経路との重要な違い: Hough は 9 スライス窓を 1 枚に z 射影（`zpj`）して
z を捨てる。グラフ検出器は z 方向全体を要するため、**各スライスを個別に
二値化**（`module.preprocess` の fog 除去 → Otsu → ノイズ除去を再利用）し、
前景画素をすべて 3D ヒットとして出力する。シミュレーションの `Ev_*.xlsx` の
Summary/飛跡別シートは実データにない正解情報なので、`sheet`/`id` は 0 の
プレースホルダ、`n` は fog 除去後の強度を持たせる。

### 実装

`module/matlab_export.py`（`export_hits` ＋ `save_mat`、薄い CLI）。
`run.py matlab-export` として配線。座標は 1-based（x = col + 1, y = row + 1,
z = slice + 1）で MATLAB の (1, 1, 1) 原点と `x > lb` / `x <= ub` の小領域
分割に合わせる（0-based だと最初の行/列が落ちる）。出力は `scipy.io.savemat`
で `pl`（N×6 float64）＋ `variablenamespl`、圧縮あり。

### 試作結果とスケーリングの注意

タイル V00000004（2048×2048×58）: **22,072,518 ヒット**、x,y ∈ [1, 2048]、
z ∈ [1, 58]、n ∈ [3, 119]；圧縮 `.mat` ≈ 38 MB；`myenv`（cv2+scipy）で約 27 秒。
`scipy.io.loadmat` で往復を検証。

注意: これは MATLAB が調整されたシミュレーションイベント（2048×2048×80 で
~10⁴ 点）より約 1000 倍密。`mabiki(.,3)` で ~9× 削減されるが、
`detectlseg_smallregion` は 128×128×80 の各小領域内で `pdist`（O(N²)）を使う
ため、MATLAB 側のダウンサンプル、場合によっては Python 側のより強い
ノイズ除去（`--noise-*` フラグを公開済み）が、グラフ段を現実的にする上で効く。
ユーザーに共有済み。エクスポート契約自体の欠陥ではない。

---

## 2026-07-11 — MATLAB エクスポート試作をコミット；ToDo 整理

2026-06-23 の試作（`module/matlab_export.py`、`run.py matlab-export`、
README / 日記 / discussion の更新）はユーザー確認待ちで未コミットのまま
だった。本日ユーザー承認が出たので、一式を 1 つの feature コミットとして
`main` に載せ、`origin/main` へ push する。2026-06-23 以降コードの変更は
なし。本エントリはコミットの記録と ToDo の現状整理。

### ToDo（持ち越し）

- **密度／計算量。** タイル V00000004 のエクスポートは 22,072,518 ヒットで、
  MATLAB 検出器がチューニングされたシミュレーションの約 1000 倍。対策の
  配分を決める：Python 側ノイズ除去の強化（公開済み `--noise-*` フラグ）
  vs. `mabiki(pl, 3)` を超える MATLAB 側ダウンサンプリング。
- **MATLAB 実走。** `V00000004_..._pl.mat` を
  `e07/matlab/detect_tracks.m` に入力し、`detectlseg_smallregion`
  （128×128×80 領域ごとに `pdist` O(N²)）の実行時間・メモリを計測して
  から複数タイルへ展開する。
- **出力置き場の規約。** 試作 `.mat` はセッションの scratchpad にある。
  リポジトリ側の規約（例: `results/matlab/`）を決め、その後に複数タイル
  一括エクスポートを追加。
- **パイプライン側の積み残し（本スレッド以前から）。** 重粒子起因の偽
  バーテックスに対する角度広がりフィルタ込みのバーテックス候補レビュー、
  `hough_ml=30` の再実行。
