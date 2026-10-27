# STATUS — 現在の状態（e07-fullscan）

**最終更新: 2026-10-27**

このファイルは「**今どうなっているか**」だけを書く。**追記ではなく
上書き**する（変遷は `git log -p STATUS.md` で追える）。
経緯・失敗した試み・議論は `analysis-note.md`（逆時系列の開発日誌）
が一次資料。矛盾したら analysis-note.md の**新しい方**が正。

**データがどう流れているか**（4段の構成、各段のエントリポイント、
出力先、本番パラメータ）は `pipeline.md` に分けてある。
このファイルは「**どれくらい上手くいっているか**」を書く。

新しいセッションはまずこのファイルを読めば、現在地が分かるようにする。

---

## 手法の現状

パイプラインは 4 段：① 生画像 → ② 前処理 → ③ 線分検出（Hough）
→ ④ 反応点(vertex)検出。どの手法もこの段構成を共有する。

| Method | 内容 | ML | 状態 |
|---|---|---|---|
| **A** | Pure Python（`find_tracks`→`find_vertices`→`merge_vertex_slices`） | 不使用 | **主軸。全域再解析 完了（2026-09-09）**。12.4億トラック → 反応点 1,516,569 個。④の precision が未解決 |
| **B'** | グラフ検出器（`export_hits_grid`→`detectlseg`→`integrate_smallregions`→`detectbunki`） | 不使用 | **移植完了・実 E07 で走る**。cell=30 は45分/view だが purity が出ない。**cell=6＋分類器フィルタは e07-srv で 1 view 約 5.6 分**（エクスポート約100 s＋段1 106 s＋段2 120 s＋段3 11 s、2026-10-23）。ただし 1 view で branch point 30,308 個＝**段3 の purity 問題が全域規模で残る**ので全域実行は保留 |
| **C** | CNN 生画素セグメンテーション（別リポジトリ `e07-ml-binary-segmentation`） | 使用 | **注力対象。弱い判別力が出た段階**（LOTO・セグメント単位で AUC 0.59、precision 49.5% > 基準率 43.6%）。実用には遠い |
| **D** | 教師なしクラスタリング（KMeans/GMM） | 使用 | **失敗確定・打ち切り**（precision 46〜50%＝ほぼチャンス） |

Method A/B が共用する補助部品として、手作り特徴量分類器
`module/track_classifier.py`（6 特徴量ロジスティック回帰）がある。
③と④の間のノイズ除去、および Method C の疑似教師データ生成に使う。

---

## 点群（グラフ検出器に渡す hit）の評価 — 2026-10-27 時点

合成データ（e07-g4-hypernuclei v19）で点群とグラフ検出器の出力を測る。
詳細は analysis-note.md 2026-10-27 15:30。

- 候補 dog3dz K2（GPU の 3D DoG＋放物線当てはめの z）を、凍結した基準で
  held-out の v19_synth_eval2_dz4（10 視野）に一度だけかけた。
- **点群としては合格**: 背景飛跡の粒子を拾う割合が classifier の 4 倍以上、
  信号飛跡の全損 3 本（classifier 22 本）、dz p90 が classifier 以下。
- **グラフ検出器に通すと 2 項目で不合格**: 偽の折れ線の長さが背景の少ない
  視野で production の約 3 倍（基準 2 倍）、処理時間の比の最大 2.53（基準 2.5）。
  信号飛跡の一致（best_good 0.42 対 0.17）や背景飛跡の被覆は大きく良い。
- **本番は置き換えない。** 次は段2 の偽の抑制を v19 tune で調整し、
  未使用の新しい組で評価する（eval2 は使用済み）。
- 合成の深さ応答は実データより約 15% 狭いので、z 精度は楽観的な値。

---

## Method B' — MATLAB グラフ検出器の Python 移植

**MATLAB は kekcc に無い**（PATH にも `/sw/packages` にも無し）。実行
できるのは macbook の R2026a だけで、1 view 約9.2時間かかる。全域
2025 view は約2.1年になり不可能。またシミュレーション用の定数が
E07 に合っているか検証できない。この2点を同時に解く手として、
`e07/matlab` の 1,096行を `module/graphdet/` へ移植した。依存は
numpy + scipy のみ。

| 段 | MATLAB | 状態 |
|---|---|---|
| 1 | `detectlseg_smallregion` | **完了**（2026-08-22）14.0 秒/view |
| 2 | `integrate_smallregions` + `pixellist2poly` | **完了**（2026-09-07）10.5 秒/view |
| 3 | `detectbunki` | **完了**（2026-09-07）1.0 秒/view |

**移植は完了。次は Phase 2（E07 への較正）。**

**検証に MATLAB は要らない。** `e07/matlab/work1.mat` が入出力の対を
持っている（シミュレーション事象1の 41,609点 → `lseg` 1,239線分 →
`polylines` 149本）。照合は
`python scripts/check_lseg_reference.py`（段1）、
`python scripts/check_polylines_reference.py`（段2）、
`pytest -m slow tests/test_graphdet.py`（両方）。

- **段1**: 1,239 セグメント**全一致**、最大端点誤差 2.5e-13 px。
- **段2**: polylines **149本ちょうど**、全長 118,270 px（参照 118,033、
  差 0.2%）、全ての折れ線が参照から **16 px 以内**（うち約半数はビット
  一致）。**段2は原理的にビット再現できない**——折れ線の端の頂点は
  定義上その折れ線の一番外の hit の射影なので、`resamplingpoly` の
  `ell>=0` 判定でその hit が厳密に境界に乗り、±1e-13 の丸めで採否が
  裏返る（chain 1本につき始点・終点で計2個、実測 175本全てで発生）。
  移植側は「境界 hit は常に含める」（`_ELL_SLACK_PX`、厳密演算での
  `>=0` の意味）を採り決定性を確保した。MATLAB 逐語（`>=0`）だと
  150本・最悪 76 px、「常に除く」だと hit ゼロの折れ線が出て落ちる。
  詳細は analysis-note.md 2026-09-07。

### このパイプラインの実力（2026-09-07 初測定）

`simdata8.mat` の `Summary` から**真の分岐点**を復元して測った
（10事象、真 130 個 vs 再構成 215 個、距離は等方化。
`python scripts/eval_branches.py --events 1-10`）:

| 一致半径 | efficiency | purity |
|---|---|---|
| 10 px | 93.1% | 55.3% |
| **25 px** | **96.2%** | **74.0%** |
| 100 px | 96.2% | 85.1% |

**efficiency は高く、弱点は purity**（真 130 に対し 215 個を出す）。
参考までに Method A の④は 1タイル 196〜380 候補に対し正解 1 個
なので、**桁違いに良い**。ただし一致した 125 個のうち 4 個は別の
真の分岐点と同じ頂点に潰れており、分解能はこの数字ほど良くない。
`branch_points()` は移植ではなく追加（`detectbunki` はグループしか
返さない）。詳細は analysis-note.md 2026-09-07。

### Phase 2 — 定数の較正（2026-09-07）

定数は `module/graphdet/config.py` の `DetectorConfig` に集約した。
**既定は MATLAB 値そのまま**なので参照照合は不変。要点は
**透過方向の許容値と長さスケールを分けた**こと——前者
（`th_split`、`attach_max_dist`）は軌跡の幅と測定誤差なので間隔と
一緒にスケールしてはいけない。後者（`grow_margin`、`end_reach`）は
しなければならない。`for_spacing()` が後者だけを直す。

**測定した最大の事実: 現 export の 30 px 格子は粗すぎる。**
同じシミュレーションを別ブロックで間引き直して測った
（`python scripts/scan_sampling.py --events 1-3`、真値41個）:

| block | efficiency | purity |
|---|---|---|
| 3（シミュレーション） | 92.7% | **78.8%** |
| **6** | 85.4% | **75.9%** |
| 10 | 75.6% | 58.9% |
| 20 | 48.8% | 20.6% |
| **30（旧 export）** | 53.7% | **17.5%** |

段ごとに切り分けると**段1・段2 は 30 px でも無傷**（軌跡長 98%、
真の頂点 14/14 の近くに折れ線の頂点がある）。**壊れるのは段3だけ**で、
`detectbunki` が「1.5 px 以内で共有された hit」で分岐を判定するため。
定数では直らない（`attach_max_dist` を 1.5→12 に緩めても
efficiency 57→64% で頭打ち、purity は 30→4% に悪化）。
「折れ線の端点が別の折れ線に近い」という幾何判定の代案も試作したが、
efficiency は 83% に戻るが purity は 26% 止まりで**不採用**
（数字は analysis-note.md 2026-09-07 に記録）。

→ **`matlab_export._GRAPH_CELL_PX = 6` を新設**し export と CLI の
既定にした。30 px は 2026-07-11 に **MATLAB を 2.5時間/tile に収める
ため**に選ばれたもので、移植で約250倍速くなった今その制約は無い。
ノイズフィルタと viewer overlay は 30 px で別途チューニング済みなので
`_GRID_CELL_PX = 30` のまま分離した（`noise_cell` 引数）。

**2026-09-08 に実測した（上のリスクの回答）**: 実 E07 タイル1枚で
end-to-end が通るようになった。**合計 約45分/view**（エクスポート 80 s
＋ 段1 2,449 s ＋ 段2 163 s ＋ 段3 10 s、cell=30）。そこに至るまでに
**厳密な最適化を3件**入れた（参照照合は不変）:

1. `refine_endpoints` は端点をずらしても変わるのは**そのセグメントの
   列だけ**。他は1パス1回に。N=800 の region が **176.9 → 4.23 秒**、
   指数 2.6 → 1.6。
2. 段2 の端点探索を **k-d tree** に（箱の半幅で割ると Chebyshev 球）。
3. `_resample` と `attachment_codes` の**全 hit 走査を近傍クエリ**に。
   段2 8.1→0.9 秒、段3 0.8→0.3 秒（シミュレーション）。

さらに段3 は表現を変えないと実データで動かなかった:
`attachment_codes` の密行列が **7 GB**（4 GB 制限超）、
`branch_points` が **8.4億ペア**。疎行列＋junction hit を歩く形に。

cell=30 の出力は使えない（折れ線 28,988本＝シミュレーション 149本の
約200倍に断片化、branch point 8,118個＝同13個）。これは
シミュレーションが示した「30 px では purity 17.5%」と整合する。

**cell=6 を使えるようにした（同日 22:00）。** 打ち手は2つ:

1. **エクスポートのノイズフィルタを分類器モードに**（既存512ラベルで
   学習、人手追加なし）。cell=6 で hits 1,667,324 → **784,522**（2.1倍減、
   3,065/region）。なお `threshold` モードは legacy より甘く10倍遅いので
   使う理由が無い。
2. **`_merge_overlapping` を全セグメント同時計算に**（`refine_endpoints`
   を直した後は段1の85%を占めていた）。N=3,013 で 331.8 → **39.0 秒**。

| | cell=30 (legacy) | **cell=6 (classifier)** |
|---|---|---|
| hits/region 中央値 | 972 | 3,024 |
| エクスポート | 80 s | 853 s |
| 段1 | 2,449 s | **約 2.77 h** |
| シミュレーションでの purity | 17.5% | **75.9%** |

（上表は kekcc での値。）**e07-srv での高速化（2026-10-23、
V00000991、754,765 hits、出力はすべてビット一致・MATLAB 参照テスト通過）**:

| | 旧（e07-srv 実測） | 新 |
|---|---|---|
| エクスポート 1 スライス | 16.5 s | **1.7 s**（GPU） |
| エクスポート 1 view（58 枚） | 540 s | **約 100 s** |
| 段1 最密領域（5,464 hits） | 94 s | 約 10 s |
| 段1 1 view | （kekcc 2.77 h、e07-srv 旧版は未計測） | **106 s**（12 プロセス） |

段1: `_merge_overlapping` を変わった列だけ更新（重なり・行数・共有数・
行最大を差分管理）、端点調整の候補 9 本を一括＋候補の外接箱内の hit
だけ評価、SVD を thin に、`detect_lseg_view(workers=N)` で領域並列。
全 (N, M) 走査が残っていると並列化がメモリ帯域で頭打ちになる
（12 並列で 451 s → 差分化後 106 s）。エクスポート: `_footprint_width`
を全線分一括（GPU、torch）、`_measure_tracks` の線分×粒子の距離を GPU
で候補抽出→CPU で元の式で判定。GPU が無ければ numpy（`E07_DEVICE` で
指定可）。段2 120 s（折れ線 32,341 本）、段3 11 s（branch point
30,308 個）。**1 view 約 5.6 分、全域 2,025 view は単純計算で約 8 日。**
ただし branch point が 1 view 3 万個では全域で 6 千万個になり、段3 の
purity が解決するまで全域実行の意味は薄い。

**定数スケーリングの分類（2026-09-08 に測り直した）**: `for_spacing()`
は**間隔スケール群だけ**を直す。全部スケールすると cell=30 で端点探索箱が
50→500 px になり、purity が落ちる上に段2 が二次オーダーになる
（実タイルで60分超→154秒の差）。3群の内訳:
- **間隔スケール**（次の hit までどれだけ探すか）: `grow_margin`、
  `refine_dl*`、`single_point_max_dist`。**これだけスケールする。**
- **透過方向の許容値**（軌跡の幅＋測定誤差）: スケールしない。
- **軌跡幾何のギャップ**（断片同士の距離、vertex への届かなさ）:
  `neighbour_xy`、`end_reach`、`vertex_merge`。物理と小領域格子が
  決めるのでスケールしない。

**まだ切り替えていない定数**: `z_scale`。既定は MATLAB の
`3.0/0.29`（3µm スライス前提）だが E07 は **1.5µm/スライス**なので
`config.E07_Z_SCALE = 1.5/0.29` を用意してある。シミュレーションでは
検証できない（そちらは 3.0/0.29 が正しいため）。

---

## グラウンドトゥルース: specials_x20 の乾板内訳

**`specials_x20/` の 13 ディレクトリ中 11 は E07 乾板**であり、実 E07 の
本物の反応点データとして使える（2026-07-27 ユーザーより）。

| 乾板 | ディレクトリ |
|---|---|
| **E07（11）** | D005, D013, IBUKI, IRRAWADY, MINO, T004, T004_3body, T004_center, T011, T011_100, T011_200 |
| **E373（2）** | KISO, NAGARA — **当面優先度低** |

`tests/specials_gt.json` に実測 vertex 座標があるのは 9 事象で、
**うち 7 事象が E07**（D005, D013, IBUKI, IRRAWADY, MINO, T004, T011）。
残り 2 事象（KISO, NAGARA）は E373。
E07 の T004_3body / T004_center / T011_100 / T011_200 は
**データはあるが GT 未測定**——クリックすれば GT を増やせる。

→ **実 E07 の GT 付きデータでパラメータ最適化・評価ができる。**
以前の「specials は E373 なので最適化対象にするな」「実 E07 に
確認済み反応点は 1 件も無い」という制約は**誤りだったので撤回**。
前景密度が約 1.8〜2 倍違うという実測（2026-07-15）は
**KISO(E373) と E07 全面探査データの比較**であって、specials 全体の
性質ではない。

---

## 現時点の最良数値（測定条件込み）

**分類器（`track_classifier.py`）** — 実ラベル 512 件、4 タイル
leave-one-tile-out：

| | precision | recall |
|---|---|---|
| 平均 | **85.5%** | 83.1% |
| タイル別レンジ | 78.1〜91.9% | 58.5〜96.4% |

**③ Hough 検出の recall**（確認済み実飛跡ピクセルに対する被覆率、
4 タイル平均、thr=35/ml=30 固定）:

| max_gap | recall | raw候補数 |
|---|---|---|
| 5（旧本番） | 45.8% | 559 |
| **40（現本番）** | **92.7%** | 10,173 |
| 80 | 97.2% | 6,008（ただし偽ブリッジ急増） |

**④ vertex 検出** — `specials_x20` の既知 ΛΛ ハイパー核 9 事象で
`tests/test_specials.py` が 35/35 通過（recall）。
**注意（2026-10-23）: 下の順位の多くは偶然一致の水準。** 候補 ~750 件では
XY 200 px の円に偶然 ~23 件入り、真値を乱数でずらした点も 78〜100% が
「見つかり」中央値 25〜62 位になる。偶然を明確に上回るのは D005・D013
だけ（IRRAWADY・T004 は境界、IBUKI・MINO・T011 は偶然並み）。評価は
位置を詰めた一対一照合と偶然対照で行う（analysis-note 2026-10-23）。

**正解付き疑似画像での評価（2026-10-23、e07-g4-hypernuclei、実 view 埋め込み
v3、100 事象）**: 手法 A の XY は数 µm（最近傍の中央値 5〜6 µm、偶然 9 µm）
と偶然より正確（ただし 6 µm 以内は 46〜59%）。**深さが主要課題**（z 範囲の
端は偶然並み、新設の `z_best` が最良だが撮影範囲の端で中央へ寄る。原因は仮説）。
偶然との差は関連の指標で、効率そのものではない。捕獲点の一対一効率は inclusive <6 µm
で 28〜42%（偶然 9〜10%）。表は `~/work/e07-g4-hypernuclei/output/
efficiency_report.md`（`./run.py evalreport` で再生成）。

**既知 vertex の順位（2026-10-23 測り直し、`scripts/rank_specials.py`）**:
本番カットで E07 7 事象すべて検出、`n_tracks_max` 降順の
**順位は中央値 13、最悪 64**（2026-09-09 の「中央値 6、最悪 48」は
z 判定が実質無効だった版。下記）。

| 事象 | 候補数 | 本番 | relaxed | | 事象 | 候補数 | 本番 | relaxed |
|---|---|---|---|---|---|---|---|---|
| D005 | 751 | **1** | 2 | | T004 | 733 | 13 | 25 |
| D013 | 404 | **3** | 5 | | MINO | 691 | 50 | 30 |
| IRRAWADY | 223 | **4** | 7 | | T011 | 123 | 59 | 19 |
| IBUKI | 687 | 64 | 34 | | （E373: KISO 22, NAGARA 198）| | | |

**z 判定の不具合（2026-10-23 修正）**: z はステージ座標 mm（刻み
0.0030）なのに、真値ファイルの `z_um`（実は mm を 0.1 mm に丸めた値）と
`tolerance_z_um = 30` を直接比べており「30 mm 以内」＝無制限だった。
今は真値 z をクリックしたスライス `z_slice` から取り、**クリック深さが
候補の `z_min`〜`z_max`（±30 µm）に入るか**で判定する（`z_mean` は星の
片側にずれるため使わない）。`rank_specials.py`、`rank_features.py`、
`tests/test_specials.py` が同じ判定。物理的な z 刻み（ステージ 3.0 µm か
乳剤中 1.5 µm か）は**ユーザーに確認中**。
→ view ごとに上位50件では 5/7、7/7 には上位64件が要る。relaxed カットの
方が IBUKI・MINO・T011 で順位が良く、「本番カットは真値を捨てていない」
とは言い切れなくなった。

**単一特徴量での順位（2026-10-23 測り直し、`scripts/rank_features.py`）**:
旧版は 200 px 内で **n_tracks_max 最大の候補を真値に選んでから**比較して
おり n_tracks_max に有利だった。真値を XY 最近傍で決め直すと、中央値は
`n_tracks_max` 13 / `n_slices` 60 / `mean_intens` 82 /
`angle_spread_max` 132 / `angle_spread_best` 172 / `z_extent` 153。
一致候補のどれかの最良順位（全特徴量に等しく甘い）では `z_extent` 10
（上位10に 4/7）、`n_tracks_max` 12（3/7）、`angle_spread_best` 22。
**7 事象では特徴量の優劣は決められない。** 2026-09-11 の「n_tracks_max が
桁違いに強く他は全滅 → 物理フィルタ必須」は真値選択の偏りに依存して
いたので撤回（物理フィルタが要らないという意味ではない）。
`merge_vertex_slices` の出力が member track を持たない点は変わらない。

**④ precision の監査を準備（2026-10-23、`scripts/vertex_audit.py`）**:
v7 全候補を、view 内 `n_tracks_max` 上位20 と `angle_spread_best ×
n_slices` 上位20（同順位は乱数で崩し、どちらも view あたりちょうど20）
で 4 層（両方 4,191 / n_tracks のみ 36,309 / sp×nsl のみ 36,309 /
どちらでもない 1,439,760）に分け、各100件を無作為抽出。うち各層10件の
**予備監査 40 件**の画像（概観＋z 範囲の全スライス、判定画面でスライス
送り）を作成済み（`results/vertex_audit_v7/`）。判定（vertex / crossing /
track / junk / unclear）は未着手、ユーザー判断待ち。過去の監査:
v6 の n_tracks_max 上位は 204/204 bad、sp×nsl 上位 200 件は good 70 /
bad 46 / unclear 84。

---

## 本番パラメータ

**正典は `config/default.yaml` の `viewer` ブロック**。
`module/pipeline/finder.py` は 2026-07-27 からこの yaml を読む
（それ以前はハードコードで、2 回ずれて 2 回とも検出性能を劣化させた）。

現在値: `zpj_half=4, fog_ksize=51, noise_amin=2, noise_amax=100,
noise_cmp=50, noise_amax_upper=0, hough_thr=35, hough_ml=30,
hough_mg=40, grain_radius=15, px_scale_um=0.29`

**yaml を読まない例外**（意図的に別値、変更時は注意）:
- `module/server/labeling.py` — 2026-07-23 に本番値へ統一済み
- `module/matlab_export.py` の `_NOISE_V2_*` — thr=8/ml=10/mg=20
  （Method B のノイズフィルタ用、分類器の学習データと整合）
- `module/pipeline/diag_common.py` の `TRACK_CFG` — yaml のミラー、
  手で同期している（将来 yaml 読み込みに寄せる余地あり）

---

## いま効いている制約・注意

0. **人手レビューは `/label_disagree` を使う（2026-07-29）。**
   古典分類器と CNN が食い違う順に候補を出すブラウザ UI。両者が一致
   している候補を見ても情報が増えないので、不一致だけを潰すのが
   クリックあたり最も効率が良い。本番パラメータの 47,498 候補のうち
   **30.2% は判定が真逆**、確率差 0.7 超も 396 件あり、キューは十分厚い。
   起動は `python -m module.server.app --port 8123` → ブラウザで
   `/label_disagree`。初回のみ約 80 秒のキャッシュ構築、以降 0.12 秒。
   CNN スコアはチェックポイント依存なので、モデル更新後は ML 側の
   `dump_segments.py --all-candidates --hough 35,30,40` と
   `score_candidates.py` を回し直すこと。

1. **ラベルファイルは Hough パラメータごとに分かれる（2026-07-29）。**
   決定は候補リストへの添字なので、パラメータが違えば別物を指す。
   既存 512 判定は 8/10/20、レビュー既定値は 2026-07-23 から 35/30/40。
   以前は新規クリック 1 つで既存判定が全て別候補を指すよう静かに
   書き換わる状態だった（実害が出る前に修正）。現在は
   `..._z29.json`（8/10/20）と `..._z29__t35l30g40.json` のように
   別ファイルへ書く。**両者は別の母集団**なので、単純に合計件数として
   数えないこと。

2. **Method C（CNN）の判別力は弱く、AUC 0.59 で頭打ち（2026-07-28）。**
   ラベルを増やしても動かなかった: E07 specials の反応点から放射する
   飛跡を正例に加え学習タイルを 3→9 に増やしたが、**AUC 0.592 → 0.594**
   と変化なし（検出限界は 0.07 AUC）。判別すべきは「線状の junk」と
   「線状の本物」の区別で、specials は「本物だ」しか教えないため
   効かなかったと解釈。**足りないのは正例ではなく junk/track を分ける
   情報**で、次は人手レビュー（古典と ML の不一致箇所を優先）か、
   スライス間 3D 整合性など別種の信号。

3. **同 AUC 0.59 に至った経緯。**
   セグメント単位・LOTO（4 タイル × 3 seed × 2 arm、n=1536）で
   precision 49.5%（基準率 43.6%、CI 下限も基準率超）、AUC 0.582/0.597。
   当初は AUC 0.55・precision＝基準率ちょうどで判別力ゼロだったが、
   **背景を負例として損失に入れる**修正で改善した（マスクの 99% が
   `-1` のため、それまで「何もない乳剤」を一度も負例として見せて
   いなかった）。ただし**層内では基準率との差が有意でない**ので、
   全体 AUC の一部は層の混合比を当てているだけの可能性が高い。
   残る壁はデータ量（学習に使えるのは 3 タイル）。詳細は Method C 側
   STATUS.md。

4. **Method C（CNN）の過去の数値は誤差を約25倍過小評価していた。**
   人間が判定したのは Hough セグメント単位なのに、precision/recall を
   **画素単位**で数えていた。検証タイルは 40,016 ラベル画素あるが独立な
   単位は **63 セグメント**しかなく、95% CI は ±0.4pt ではなく **±9.1pt**。
   「seed だけで precision が 6.6pt 動く」現象はこの範囲に完全に収まる
   ——モデルが不安定だったのではなく誤差棒の分母が違っていた。
   → 2026-07-28 に `eval_segments.py`（セグメント単位＋Wilson 区間＋
   ランク層別）へ移行。詳細は Method C 側 STATUS.md。
   4 fold 統合でも分解能は **±3〜4pt が上限**なので、それ以下の差は
   現ラベル量では原理的に主張できない。

5. **ラベルは候補母集団の代表サンプルではない。** ラベル作成時の Hough
   （thr=8/ml=10/mg=20）は 1 タイル 24,038 本の候補を出すが、人間が見たのは
   63 本＝0.26%。しかも上位100位以内（track 率 71%）と 1000位超
   （track 率 4%）の二峰性。報告時は層別を併記すること。

6. **全域カタログは再生成済み（2026-09-09、この制約は解除）。**
   本番パラメータ（mg=40）での全 2,025 view:

   | 段 | 場所 | 件数 | サイズ |
   |---|---|---|---|
   | ③ トラック | `results/fullscan_v7/chunk_*.parquet` | **1,244,606,615** | 26 GB |
   | ④ 反応点（スライス毎）| `results/vertex_v7/vertex_*.parquet` | **16,728,649** | 572 MB |
   | ④ マージ後 | `results/vertex_v7/vertices_merged.parquet` | **1,516,569** | 62 MB |

   所要 約1.5時間（LSF queue `p`、同時120本）。実測 ③ 1 view = 125〜134
   秒 CPU / **1.2 GB**、④ 1 chunk = 約20秒 / **0.7 GB**。
   旧 `results/`（2026-05-14、mg=5）は残してあるが**もう使わない**。
   **1.52M という数はそのまま④の precision 問題である**——物理ベース
   フィルタ（PID、頂点運動学）が必須であることの再確認。

7. **mg=40 の④への影響を測った（2026-09-08、この制約は解除）。**
   実 view 1枚、mg=5 との比較:

   | | mg=5 | mg=40 |
   |---|---|---|
   | tracks/view | 47,490 | 634,577（13.4倍）|
   | 品質カット後 | 2,340 (4.9%) | 6,653 (1.0%) |
   | vertex 候補 (n≥3) | 193 | 2,533（13.1倍）|
   | 最大多重度 | 7 | **19** |
   | n≥8 の候補 | **0** | **66** |

   候補は13倍（全域で約5.1M）に増えるが、**mg=5 では高多重度の星が
   原理的に見えない**（この view で n≥8 がゼロ）。ΛΛ の一次反応点は
   高多重度なので、これは単なるノイズ増ではない。
   **全域再解析は投げてよい。ただし④のフィルタ強化が同時に要る。**

8. **重い I/O を iCloud Drive 上に置かない。** macOS 側の `~/work` は
   iCloud へのシンボリックリンク。CNN 学習が 22 時間ハングした
   （`STAT=UN`、CPU 時間 11 分のみ）。
   → E07 データは `~/out-of-sync/e07/fullscan/`、
   CNN の `data/`・`results/` は `~/out-of-sync/e07-ml/` に退避済み。

---

## 次にやる候補

- **cell=6＋分類器フィルタで実 E07 タイルを end-to-end で通す**
  （現在の最優先）。段1 に約2.77時間かかるのでワークサーバではなく
  **LSF queue `h`**（walltime 8日、4 GB。段1 のメモリ実測 0.3 GB）へ。
  ここで得た折れ線と branch point が、シミュレーションの
  purity 75.9% に見合うかを実データで初めて見られる。
- **`denoise_method` の既定を分類器モードにするか決める**。学習済み
  モデルを渡す必要があるのでエクスポート CLI 側の手当てが要る。
  現状の既定は `legacy`。
- **`z_scale` を `E07_Z_SCALE` に切り替える**。実データでしか検証
  できない。
- **specials_x20 の既知 vertex で分岐グループの順位を見る**。
  ここで要る人手は **GT vertex のクリックだけ**（T004_3body /
  T004_center / T011_100 / T011_200 の4事象が未クリック）。
- **Phase 2: 定数を E07 に較正**。z_step 1.5µm、`_GRID_CELL_PX`、
  直線性の TH。目的関数は既知 vertex での分岐グループ数と順位。
  ここで要る人手は **GT vertex のクリックだけ**（T004_3body /
  T004_center / T011_100 / T011_200 の4事象が未クリック）。
- **飛跡抽出を古典・ML の 2 手法で確立する**（現在の目標、反応点より前）。
  Method C 側は 2026-07-28 に方向ヘッドを追加し、`extract_segments.py`
  で CNN 出力から Hough を通さずに線分（端点・長さ・角度）を取れる
  ようにした。これで ML が古典の前処理ではなく**独立した抽出器**になる。
- **古典と ML が食い違う場所を優先レビューする。** 2 手法を持つ最大の
  利点で、長い順に見るより labour あたりの情報量が桁違いに高い。
  「人が画素を塗るのは大変」という制約への現実的な答え。
- ~~**E07 specials から正例を自動生成して学習に足す**~~ — 2026-07-28 に
  実施したが **AUC 0.592 → 0.594 で帰無**。学習タイルを 3→9 に増やして
  も判別力は動かなかった。仕組み（`specials_label_dataset.py`、
  `--specials`）は残してあるが既定では使わない。ただし**評価専用の
  非循環セット**としての価値は残る——反応点から放射する線分は Hough の
  提案に依存しないので、「Hough が見逃した飛跡」も評価に含められる
  （現在のラベル 512 件はすべて Hough 候補の中にしか存在しない）。
- **④の precision を上げる物理ベースフィルタ**（本命）。
  dE/dx による粒子識別、MC による頂点運動学の整合性チェック。
  「あれば良い追加」ではなく**必須**であることは定量的に裏付け済み。
  grain_density は px_scale=0.29 / grain_radius=15 の修正で
  0.57 → 14.77 grains/100μm と物理的に妥当なオーダーに入った
  （2026-07-27 実測）ので、PID の前提は整った。
- **GT を増やす**。E07 の T004_3body / T004_center / T011_100 /
  T011_200 は未クリック。人手ラベル拡充も両手法の評価を安定させる。
- 分類器への特徴量追加、トリアージ結果（`results/pseudo_label_review/
  flagged.json`）の人手レビュー反映。

---

## 環境

- **macOS**: `~/work/e07/e07-fullscan`（= iCloud 上）。
  E07 データは `fullscan-image/E07` → `~/out-of-sync/e07/fullscan/`。
- **kekcc**: `~/work/e07/e07-fullscan`（2026-07-27 に `fullscan` から
  rename して macOS と名前を統一。`~/work` 自体が gpfs 実体への
  シンボリックリンク）。E07 データは
  `/gpfs/group/had/sks/E07/tohoku/fullscan/E07/MOD108/PL12/tohoku-v1/
  AREA00/IMAGE00_AREA00`（2025 タイル / 259 GB）。
  Method C のリポジトリは **`e07-ml-binary-segmentation`**（2026-09-09
  に GitHub の改名が判明し、remote URL・kekcc のディレクトリ名とも
  新名へ揃えた。旧名は `e07-binary-segmentation`）。
  **macOS 側は元から `e07-ml-binary-segmentation`** だったので、
  これで三者（macOS / kekcc / GitHub）の名前が揃った。
- **主作業機は e07-srv（2026-10-23〜）**: Ryzen 9 9900X 12C/24T、
  122 GB、RTX 5070 Ti 16 GB。④ まで kekcc ではなくここで行う方針
  （ユーザー判断）。tohoku-v1 全 2,025 view（307 GB）がローカル
  （`fullscan-image` → `~/microscope-image/tohoku/fullscan`）。
  Python は `~/work/.venv`（3.12、OpenCV 5、numpy 2）。kekcc とは
  候補数が ±1〜2 ずれる事象がある（OpenCV/numpy の版差と推定）。
  `vertex_v7` カタログと specials 成果物は kekcc からコピー済み。
  **実装はなるべく GPU に切り替える**（ユーザー方針。kekcc 用に CPU
  経路は残す）。
- **kekcc の Python**: conda `myenv`
  （`/home/had/hayashu/.conda/envs/myenv/bin/python`、py3.9）が
  プロジェクト環境。既定の py3.12 ではない。cv2 4.12.0 / scipy /
  pandas に加え、2026-07-27 に scikit-learn 1.6.1 /
  scikit-image 0.24.0 / torch 2.8.0+cpu / torchvision 0.23.0+cpu を
  導入。**numpy は 1.26.4 に固定**（conda/pip 混成環境なので
  numpy を上げると conda 版 opencv が壊れる）。
- **kekcc に MATLAB は無い**（PATH にも `/sw/packages` にも無し。
  あるのは ansys のみ）。MATLAB が動くのは macbook の R2026a
  だけ。これが Method B' を Python へ移植している理由。
- **kekcc のバッチ**: `bsub` は使える（LSF 10.1、cw07 で確認）。
  投入可能 queue は `s l h p a`（全て MEMLIMIT 4 GB）。
  `s`=300分だが pending 4.4 万件で大渋滞、`h`=11520分（8日）。
  **GPU は使えない**——queue `g` はアクセス権が無く（`USERS: shogo
  kmura ce_ibm/`）、`Closed:Inact_A`、唯一の GPU ホスト `ccg01` も
  `unavail`。CNN 学習は CPU 実行になる（`torch.set_num_threads()` は
  TASKLIMIT に合わせ 12 以下に）。
- **kekcc ワークサーバ（cw07）は 1 ユーザ 4 コアに制限される。**
  CPU を食う対話プロセスは cgroup `/user.slice/restricted_user` に
  移され、`cpu.max = 400000 100000`＝**全プロセス合計で 4 コア**
  （128 コアのノードでも）。最初の数十秒だけ全速で走り、その後
  約 1/16 に落ちる。落ちている間もマシンは 96% アイドルに見えるので
  紛らわしい。`ps` の `%CPU` は生涯平均なので瞬時値は `top` で見ること。
  → **重い計算は必ず LSF へ。** ベンチマーク前に
  `cat /proc/self/cgroup` で `restricted_user` に入っていないか確認。
- **LSF 投入は `queue: auto` で（2026-09-09）。** キュー混雑は時間単位で
  変わる（2026-09-08 夜は `h` が PEND 0、翌朝 2,820）。
  `module/pipeline/lsf_queue.py` が `bqueues -u <user>` から投入可能な
  キューを取り、CPU/wall/メモリ/**TASKLIMIT** で足切りして
  「いま起動できるジョブ数」と待ち行列の短さで選ぶ。
  **罠2つ**: queue `p` は `TASKLIMIT 2 4 64` で `-n 1` を拒否する
  （表形式の `bqueues` には出ない）。`MAX_JOB_ARRAY_SIZE = 1000` なので
  2,025 要素の配列は投げられない（自動分割する）。
- **全域再解析（Method A）は LSF に投げられる（2026-09-08、7月の
  結論を撤回）。** メモリは**チャンクあたりの view 数**に比例する:
  実測 1 view **1.55 GB**、2 view 4.35 GB、4 view 7.10 GB。
  7月の「1 worker 6.75 GB」は 4 view 相当の測定だった。
  **1 view/job なら 1.55 GB で 4 GB 制限に楽に収まる**
  （実測 2分/view、CPU 4.5分、634,577 tracks）。
  → `config/kekcc.yaml` を `n_jobs: 2025` に変更済み。
  n_jobs を減らすには view ごとの逐次書き出しが先。
- **`config/kekcc.yaml` と `scripts/kekcc_job.sh` の不具合3件は修正済み
  （2026-09-08）**: input パスの `E07/` 欠落、ジョブスクリプトが
  存在しない `module.analyze` を呼んでいた（正しくは `module.pipeline`）、
  `n_jobs: 135` がメモリ超過。出力先も `results/fullscan_v7` に分けた
  （`results/` の 2026-05-14 産物と chunk 名が衝突するため）。
  ジョブスクリプトは conda 無しノードでも `myenv` を使い、既存ファイルが
  あれば上書きせず落ちる。**2026-09-09 に投入・完走した。**
  同種の腐りが `scripts/kekcc_vertex.sh` にもあった（存在しない
  `scripts/find_vertices.py` を呼んでいた）ので修正済み。
  **必ずパイロット（`--array 1-20`）を先に投げること**——上記の
  不具合はどれも実行しないと分からず、2,025 ジョブなら 2,025 回
  失敗していた。
- **gitlab.com のリポジトリは kekcc から fetch 不可**（公開鍵未設定）:
  `pyescan` / `kinema` / `kinema.ibuki`。github 側は問題なし。
