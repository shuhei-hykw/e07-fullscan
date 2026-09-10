# パイプライン — 今どうなっているか

**最終更新: 2026-09-10**

このファイルは「**データがどう流れているか**」だけを書く。**追記ではなく
上書き**する。数値の根拠・失敗した試み・議論は `analysis-note.md`
（逆時系列の日誌）、手法ごとの現状と最良値は `STATUS.md`。
矛盾したら `analysis-note.md` の**新しい方**が正。

パイプラインを変える変更（段の追加・削除、入出力の形、エントリポイント、
本番パラメータ）を入れたら、**同じコミットでここを更新する。**

---

## 物理の目標

原子核乾板中の**ダブルハイパー核（ΛΛ）**探索。シグネチャは同一 view 内で
100〜500 μm 離れた 2 つの連結した反応点——一次（ビーム + 標的 → ΛΛ 超核）
と二次（超核の弱崩壊）。

**現フェーズはその手前**: 「あらゆる反応 vertex を取りこぼさずに見つける」。
**efficiency 最優先、purity は後回し**（ΛΛ を loss しないことが最重要）。

---

## 入力データ

| 項目 | 値 |
|---|---|
| プレート | MOD108 / PL12 / tohoku-v1 / AREA00 |
| 場所 | `/gpfs/group/had/sks/E07/tohoku/fullscan/E07/.../IMAGE00_AREA00` |
| view 数 | 2,025（45 × 45 グリッド、FOV 間隔 ~0.5 mm）|
| 1 view | 2048 × 2048 px、**58 スライス** |
| スケール | **0.29 μm/px**、z 間隔 **1.5 μm/スライス** |
| 合計 | 259 GB |

読み出しは `module/reader.py` の `load_spng()`（SPNG 形式）。

**既知 vertex 付きデータ**: `specials_x20/`（13 事象、うち **11 が E07**）。
真値座標は `tests/specials_gt.json` に 9 事象分（**7 事象が E07**、
2026-05-12 のクリック、精度 ±50〜100 px）。

---

## 全体構成

どの手法も 4 段を共有する。**違うのは③と④**。

```
① 生画像（スライス積み重ね）
      ↓
② 前処理  fog 除去 → Otsu 二値化 → ノイズ除去
      ↓
③ 飛跡抽出   ← A / B' / C で全く違う
      ↓
④ 反応点検出
```

| Method | ③の考え方 | ④の考え方 | 状態 |
|---|---|---|---|
| **A** | 2D 投影画像の**直線**（Hough）| 飛跡の**全ペア交点** | **全域完了** |
| **B'** | 3D 点群の**折れ線**（グラフ）| 飛跡の**トポロジー**（分岐）| 実データ検証中 |
| **C** | CNN の画素単位セグメンテーション | （未着手）| AUC 0.59 で頭打ち |

---

## ② 前処理（A と B' で共通の部品）

`module/preprocess.py`:

| 関数 | 役割 |
|---|---|
| `zpj(reader, zpj_half)` | z 方向に ±zpj_half スライスを重ねる（**A のみ**）|
| `fog_remove(img, fog_ksize)` | ガウシアンで背景かぶりを引く |
| `otsu_binarize(img)` | Otsu で二値化 |
| `remove_noise(...)` | 面積・コンパクトネスで blob を落とす |
| `preprocess(...)` | 上記をまとめて実行 |

**B' は `zpj` を使わない**——3D 情報を捨てないため、スライスごとに独立に
二値化する。

---

## Method A — 古典（Hough）／**主軸・全域完了**

### 流れ

```
生画像
  │ zpj(±4) → preprocess
  ▼ cv2.HoughLinesP
飛跡セグメント          module/pipeline/finder.py : find_tracks()
  │ 品質カット（長さ・輝度・ビーム方向・角度分散）
  ▼ 全ペア交点 + 端点確認
スライスごとの vertex 候補   module/pipeline/vertex.py : find_vertices()
  │ z 方向に XY 近傍でクラスタリング
  ▼
マージ済み vertex          module/pipeline/vertex.py : merge_vertex_slices()
```

### 実行

```bash
# ③ トラック抽出（1 view/job で LSF へ）
python -m module.pipeline.cli_submit_kekcc --array 1-20      # 先にパイロット
python -m module.pipeline.cli_submit_kekcc --array 21-2025

# ④ 反応点
python -m module.pipeline.cli_submit_vertex_kekcc \
    --chunk-dir results/fullscan_v7 --vertex-dir results/vertex_v7

# マージ
python -m module.pipeline.cli_merge_chunks --input results/vertex_v7 \
    --pattern 'vertex_*.parquet' --output results/vertex_v7/vertices.parquet
python -m module.pipeline.cli_merge_vertices \
    --input  results/vertex_v7/vertices.parquet \
    --output results/vertex_v7/vertices_merged.parquet
```

`queue: auto` が投入時に一番空いているキューを選ぶ
（`module/pipeline/lsf_queue.py`）。**必ずパイロットを先に投げること。**

### 現物（2026-09-09 実行）

| 段 | 出力 | 件数 | サイズ |
|---|---|---|---|
| ③ | `results/fullscan_v7/chunk_0001..2025.parquet` | **1,244,606,615 tracks** | 26 GB |
| ④ | `results/vertex_v7/vertex_*.parquet` | **16,728,649** | 572 MB |
| ④ マージ | `results/vertex_v7/vertices_merged.parquet` | **1,516,569** | 62 MB |

所要 **約1.5時間**（LSF、同時120本）。1 view あたり ③ 125〜134 秒 CPU /
1.2 GB、④ 約20秒 / 0.7 GB。

**旧 `results/`（2026-05-14、mg=5）はもう使わない。**

### 本番パラメータ

**正典は `config/default.yaml` の `viewer` ブロック**（`finder.py` が読む）:

```
zpj_half=4, fog_ksize=51, noise_amin=2, noise_amax=100, noise_cmp=50,
noise_amax_upper=0, hough_thr=35, hough_ml=30, hough_mg=40,
grain_radius=15, px_scale_um=0.29
```

④のカット（`scripts/kekcc_vertex.sh` に埋め込み、`results/vertex_v7` を
作った設定）:

```
min_tracks=3, max_ep=150, max_ep_frac=0.5, min_intens=10, min_len=50,
max_impact=30, eps=25, beam_angle_cut=15, min_angle_spread=20
```

マージ: `eps_xy=50, min_slices=2, min_tracks=8`。

### 実力（2026-09-09、既知 vertex 7 事象）

`python scripts/rank_specials.py` — **7/7 検出、`n_tracks_max` 降順の
順位は中央値 6、最悪 48**（候補数 125〜752）。
→ view ごとに上位50件を見れば 7/7 に届く（上位15で5/7、上位6で4/7）。

---

## Method B' — グラフ検出器（MATLAB 移植）／実データ検証中

`e07/matlab` の 1,096 行を `module/graphdet/` へ移植。依存は numpy + scipy
のみ。**kekcc に MATLAB は無い**ので、これが実行手段そのもの。

### 流れ

```
生画像
  │ スライスごとに独立に二値化（zpj しない）
  │ 連結成分 → 細線化 → 6px セルごとに 1 hit
  ▼                     module/matlab_export.py : export_hits_grid()
3D hit 点群
  │ 128×128×80 の小領域ごとに最小全域木 → 直線でなくなるまで切る
  ▼                     module/graphdet/detectlseg.py : detect_lseg_view()
線分（3D）
  │ 小領域をまたいで端点をつなぐ → hit に再フィット → 折れ線同士も接続
  ▼                     module/graphdet/integrate.py : integrate_smallregions()
折れ線（＝曲がれる飛跡）
  │ 「hit が飛跡Aの胴体上 かつ 飛跡Bの端点」＝分岐
  ▼                     module/graphdet/branch.py : detect_branches()
分岐グループ ＋ vertex 座標   branch.py : branch_points()  ※移植ではなく追加
```

`branch_points()` は **MATLAB に無い追加**。`detectbunki` はグループしか
返さないが、E07 が要るのは座標なので、グループ化が既に使っている
「共有 hit」から導出している。

### 実行

```bash
# 既知 vertex 事象で測る（LSF 配列、1 事象/index）
bsub ... scripts/kekcc_graphdet_specials.sh "<event,list>" OUT_DIR PROJECT_DIR
# 中身: python scripts/graphdet_specials.py --event D005 \
#         --out results/graphdet_specials
```

### 設定

`module/graphdet/config.py` の `DetectorConfig` に全距離定数を集約。
**既定は MATLAB 値そのまま**なので、何も渡さなければ参照を再現する。

定数は3群で、**`for_spacing()` は間隔スケール群だけを直す**:

| 群 | 例 | スケールするか |
|---|---|---|
| 間隔スケール（次の hit までどれだけ探すか）| `grow_margin`, `refine_dl*` | **する** |
| 透過方向の許容値（軌跡の幅＋測定誤差）| `th_split`, `attach_max_dist` | しない |
| 軌跡幾何のギャップ（断片同士の距離）| `neighbour_xy`, `end_reach` | しない |

エクスポートは **`_GRAPH_CELL_PX = 6`**＋**分類器デノイズ**
（`denoise_method="classifier"`、既存512ラベルで学習）。
30 px は purity を 78.8%→17.5% に落とすので使わない。

### 実力

- **シミュレーション真値**（10事象・130 分岐点）: `scripts/eval_branches.py`
  で **efficiency 96.2% / purity 74.0%**（一致半径 25 px）。
- **実データ既知 vertex**（2026-09-09、6/9 完了）: 真値との距離
  **1〜8 px**（Method A は 155〜197 px）。順位は 4〜91位、候補数は
  6,000〜23,000。
- 所要: 60 スライスで約18分、200 スライス級で 0.5〜3.3 時間。

### 参照との照合（MATLAB 無しでできる）

`e07/matlab/work1.mat` が入出力の対を持つ。

```bash
python scripts/check_lseg_reference.py        # 段1: 1,239 セグメント全一致
python scripts/check_polylines_reference.py   # 段2: 149 折れ線
pytest -m slow tests/test_graphdet.py         # 両方
```

段2 は**原理的にビット再現できない**（折れ線の端の頂点が定義上その
折れ線の一番外の hit の射影なので、`ell>=0` 判定が丸め誤差で裏返る）。
曲線同士の Hausdorff 距離で測り、全折れ線が参照から 16 px 以内。

---

## Method C — CNN セグメンテーション

別リポジトリ **`e07-ml-binary-segmentation`**（GitHub 名・ディレクトリ名とも）。

```
生画像 → U-Net → 3チャンネル出力
                   ch0: 飛跡/非飛跡の binary
                   ch1-2: 方向の倍角エンコーディング (cos2θ, sin2θ)
                            ↓ src/extract_segments.py
                          Hough を通さない線分復元
```

主なエントリ: `src/train_real.py`（学習）、`src/eval_segments.py`
（**セグメント単位**評価）、`src/extract_segments.py`（線分復元）、
`src/score_candidates.py`（候補に確率を付与）。

**状態: AUC 0.59 で頭打ち。**足りないのは正例ではなく「線状の junk と
線状の本物」を分ける情報。次は人手レビュー
（`/label_disagree`：古典と CNN が食い違う順に出す UI）。

---

## 手法をまたぐ部品

| 部品 | 場所 | 用途 |
|---|---|---|
| 手作り特徴量分類器（6特徴量ロジスティック回帰）| `module/track_classifier.py` | ③と④の間のノイズ除去、B' のエクスポート時デノイズ、C の疑似教師生成 |
| 人手ラベル UI | `module/server/labeling.py` | `/label_uncertain`（不確かさ順）、`/label_disagree`（古典と CNN の不一致順）|
| LSF キュー選択 | `module/pipeline/lsf_queue.py` | 投入時に一番空いているキューを選ぶ |
| シミュレーション真値の採点 | `module/graphdet/simeval.py` | B' の efficiency/purity |

**ラベルファイルは Hough パラメータごとに分かれる**（決定は候補リストへの
添字なので、パラメータが違えば別物を指す）。単純に合計件数として数えない。

---

## いま効いている制約

- **kekcc の全 queue が MEMLIMIT 4 GB**。ワークサーバで動くことは
  4 GB で動くことを意味しない（B' はこれで2回落ちた）。
- **ワークサーバ（cw07）は 1 ユーザ 4 コア**（cgroup）。重い計算は LSF へ。
- **GPU は使えない**。CNN 学習も CPU。
- **cv2 と torch を同一プロセスに載せない**（backward がデッドロック）。
- B' の残課題: 密な事象で段1 の全点間距離行列が 4 GB を超える／
  グリッド化で重複点が生じると `coincident hits` ガードに当たる。
