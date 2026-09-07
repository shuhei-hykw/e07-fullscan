# STATUS — 現在の状態（e07-fullscan）

**最終更新: 2026-09-07**

このファイルは「**今どうなっているか**」だけを書く。**追記ではなく
上書き**する（変遷は `git log -p STATUS.md` で追える）。
経緯・失敗した試み・議論は `analysis-note.md`（逆時系列の開発日誌）
が一次資料。矛盾したら analysis-note.md の**新しい方**が正。

新しいセッションはまずこのファイルを読めば、現在地が分かるようにする。

---

## 手法の現状

パイプラインは 4 段：① 生画像 → ② 前処理 → ③ 線分検出（Hough）
→ ④ 反応点(vertex)検出。どの手法もこの段構成を共有する。

| Method | 内容 | ML | 状態 |
|---|---|---|---|
| **A** | Pure Python（`find_tracks`→`find_vertices`→`merge_vertex_slices`） | 不使用 | **主軸**。③は一通り最適化済み、④に未解決の重大問題 |
| **B'** | グラフ検出器（`export_hits_grid`→`detectlseg`→`integrate_smallregions`→`detectbunki`） | 不使用 | **移植完了（3段とも）**。シミュレーション真値で分岐点 efficiency 96.2% / purity 74.0% |
| **C** | CNN 生画素セグメンテーション（別リポジトリ `e07-binary-segmentation`） | 使用 | **注力対象。弱い判別力が出た段階**（LOTO・セグメント単位で AUC 0.59、precision 49.5% > 基準率 43.6%）。実用には遠い |
| **D** | 教師なしクラスタリング（KMeans/GMM） | 使用 | **失敗確定・打ち切り**（precision 46〜50%＝ほぼチャンス） |

Method A/B が共用する補助部品として、手作り特徴量分類器
`module/track_classifier.py`（6 特徴量ロジスティック回帰）がある。
③と④の間のノイズ除去、および Method C の疑似教師データ生成に使う。

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

**定数は MATLAB のまま**にしてある。一致が崩れたら移植のバグだと
判別できるようにするため。実データ用の較正は Phase 2 で別途行う。
特に効くもの:

- `geom.MATLAB_Z_SCALE = 3.0/0.29` — 3µm スライス前提。E07 は
  **1.5µm/スライス**なので z 距離が2倍過大。
- 全定数がシミュレーション（159本/view、飛跡に沿った点間隔 約3px）
  で調整されている。実データのエクスポートは `_GRID_CELL_PX = 30` で
  **点間隔が10倍粗い**ため、`dl=20`（伸長窓）や `err<1.5` は機能して
  いない。移植で detectlseg が桁で速くなったので、`_GRID_CELL_PX` を
  下げて density を戻す選択肢が現実的になった。

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
`tests/test_specials.py` が 35/35 通過（2026-07-27 の yaml 一元化後に
再確認、所要 29 分）。
**ただしこれは recall のみの検証**。実際には 1 タイルあたり
196〜380 個の候補が出て、正解は n_tracks 順で **7〜25 位に埋もれる**。
`_MIN_N_TRACKS=5` だけでは判別力が全く足りない。

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

6. **`results/` は 2026-05-14 で止まっており、旧パラメータ産物。**
   現在の vertex カタログ（v6/v7 pairs、ΛΛ 候補、目視ラベル）は
   すべて `hough_mg=5` 時代＝実飛跡ピクセルの 45.8% しか拾えていない
   トラックカタログの上に乗っている。**下流の物理結果は要再生成。**

7. **mg=40 はトラック数を激増させる（未評価のリスク）。**
   実測（2026-07-27、E07 実タイル 16 枚）: 618,561 本/view で
   旧 11,842 本/view の **52 倍**。n_grains 中央値は 3 と短い断片が
   大量に混ざる。④の precision が既に壊滅的なので、この密度で
   全域を回すとトリアージ不能なカタログになる恐れがある。
   **全域再解析の前に④への影響を測ること。**

8. **重い I/O を iCloud Drive 上に置かない。** macOS 側の `~/work` は
   iCloud へのシンボリックリンク。CNN 学習が 22 時間ハングした
   （`STAT=UN`、CPU 時間 11 分のみ）。
   → E07 データは `~/out-of-sync/e07/fullscan/`、
   CNN の `data/`・`results/` は `~/out-of-sync/e07-ml/` に退避済み。

---

## 次にやる候補

- **Phase 2: 定数を E07 に較正**（現在の最優先）。目的関数は
  Phase 1-3 で決まった：**真の分岐点に対する purity**（efficiency は
  既に 96.2%、伸ばすべきは purity 74.0%）。まず効くのは
  `geom.MATLAB_Z_SCALE`（E07 は 1.5µm/スライスなので z が2倍過大）と
  `_GRID_CELL_PX = 30`（実データの点間隔がシミュレーションの10倍粗い。
  移植で detectlseg が桁で速くなったので下げられる）。
  ここで要る人手は **GT vertex のクリックだけ**。
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
  Method C のリポジトリは **`e07-binary-segmentation` の名前で
  クローン済み**（`e07-ml-binary-segmentation` ではない）。
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
- **全域再解析（Method A）の所要時間**: 実測 114 秒/view、1 worker
  6.75 GB、出力 parquet 約 26 GB。ワークサーバの「16 worker で 6.5 時間」
  という当初見積もりは throttle 前の測定で、4 コア上限下では 16 時間規模。
  一方 **LSF には投げられない**（6.75 GB > 全 queue の 4 GB 制限）。
  やるなら view ごとの逐次書き出しでメモリを 4 GB 以下に落とす改修が先。
  メモリは処理 view 数に比例するので `--chunk-total`/`--chunk-id` 必須。
- **`config/kekcc.yaml` に既知の不具合 2 件**（LSF 投入時に効く）:
  `input:` のパスに `E07/` の階層が抜けている（実行時に落ちる）、
  `mem_mb: 4000` は実測 6.75 GB に対して不足。
- **gitlab.com のリポジトリは kekcc から fetch 不可**（公開鍵未設定）:
  `pyescan` / `kinema` / `kinema.ibuki`。github 側は問題なし。
