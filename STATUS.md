# STATUS — 現在の状態（e07-fullscan）

**最終更新: 2026-07-27**

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
| **B** | MATLAB 経路（`export_hits_grid`→`detectlseg`→`integrate_smallregions`→`detectbunki`） | 任意 | **休止中**（当面使わない方針、2026-07-27時点） |
| **C** | CNN 生画素セグメンテーション（別リポジトリ `e07-ml-binary-segmentation`） | 使用 | **評価手法に問題**。数値は当てにならない（下記） |
| **D** | 教師なしクラスタリング（KMeans/GMM） | 使用 | **失敗確定・打ち切り**（precision 46〜50%＝ほぼチャンス） |

Method A/B が共用する補助部品として、手作り特徴量分類器
`module/track_classifier.py`（6 特徴量ロジスティック回帰）がある。
③と④の間のノイズ除去、および Method C の疑似教師データ生成に使う。

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
`tests/test_specials.py` が 35/35 通過。
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

1. **Method C（CNN）の数値は単一実行では信用しない。**
   seed を変えるだけで precision が幅 6.6pt、recall が幅 10.9pt
   ばらつく。過去に報告した grain_radius 効果・pos_weight 効果は
   いずれもこの幅の内側で、**効果があったとは言えない**。
   改善を主張するには最低 3 seed の平均±sd が必要。
   根本原因は検証セットの小ささ（実ラベル 4 タイル中 1 枚＝55 クロップ）。

2. **`specials_x20` は E373 乾板であり E07 ではない。**
   前景密度が実測で約 1.8〜2 倍違う。既知 vertex の正解値としては
   有用だが、**パラメータ最適化の対象にしてはいけない**。
   最適化は実 E07 タイル（`fullscan-image/E07/...`）で行う。

3. **実 E07 には確認済みの反応点が 1 件も無い。** 探索対象そのもの
   なので原理的に埋まらない。複数の独立したチェックを通した候補だけ
   信じる、という設計にするしかない。

4. **重い I/O を iCloud Drive 上に置かない。** macOS 側の `~/work` は
   iCloud へのシンボリックリンク。CNN 学習が 22 時間ハングした
   （`STAT=UN`、CPU 時間 11 分のみ）。
   → E07 データは `~/out-of-sync/e07/fullscan/`、
   CNN の `data/`・`results/` は `~/out-of-sync/e07-ml/` に退避済み。

---

## 次にやる候補

- **④の precision を上げる物理ベースフィルタ**（本命）。
  dE/dx による粒子識別、MC による頂点運動学の整合性チェック。
  「あれば良い追加」ではなく**必須**であることは定量的に裏付け済み。
- **Method C の評価手法を直す**。実ラベル 4 タイルで LOTO ×
  3 seed = 12 回学習。macOS では 1 回約 2 時間なので kekcc 向き。
- **人手ラベルを増やす**。検証セットの小ささが Method C の
  評価不能の根本原因。労力は要るが両手法の評価が安定する。
- 分類器への特徴量追加、トリアージ結果（`results/pseudo_label_review/
  flagged.json`）の人手レビュー反映。

---

## 環境

- **macOS**: `~/work/e07/e07-fullscan`（= iCloud 上）。
  E07 データは `fullscan-image/E07` → `~/out-of-sync/e07/fullscan/`。
- **kekcc**: `~/work/e07/fullscan`（**名前が違う**）。
  E07 データは `/group/had/sks/E07/tohoku/fullscan/`。
  2026-07-27 時点で torch/sklearn/cv2 未導入、バッチシステム
  （`bsub` 等）が login node の PATH に見当たらない。
  詳細と対応必要事項は `HANDOFF_kekcc.md`。
- `e07-ml-binary-segmentation`（Method C）は **kekcc 未クローン**。
