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
