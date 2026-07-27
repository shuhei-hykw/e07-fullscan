# kekcc セッション引き継ぎメモ（2026-07-27 macOS セッションより）

macOS 側セッション（`claude --resume 702bbb20-...`）から kekcc 側
セッション（`claude --resume d7a92435-...`）への引き継ぎ。
重い計算を kekcc に移す話が出たので、現状と環境調査結果をまとめる。

**このメモの位置づけ**: 恒久ドキュメントではなく、この時点の
引き継ぎ用。詳細な経緯は各リポジトリの `analysis-note.md`
（逆時系列、最新が上）に記録済み。矛盾があれば analysis-note.md
が正。

---

## 1. 手法の全体像（Method A/B/C/D）

パイプラインは 4 段構成で、どの手法も「生画像 → 反応点」を一段で
解いてはいない：

```
① 生画像 → ② 前処理（フォグ除去/二値化/ノイズ除去）
        → ③ 線分検出（Hough） → ④ 反応点(vertex)検出
```

| Method | 内容 | ML | 状態 |
|---|---|---|---|
| **A** | Pure Python（`find_tracks`→`find_vertices`→`merge_vertex_slices`） | 使わない | **最有力**。エビデンス最多 |
| **B** | MATLAB 経路（`export_hits_grid`→`detectlseg`→`integrate_smallregions`→`detectbunki`） | 任意（同じ分類器） | 当面使わない方針 |
| **C** | CNN 生画素セグメンテーション（`e07-ml-binary-segmentation`、smp.Unet/resnet18） | 使う | 最弱。評価手法に問題判明 |
| **D** | 教師なしクラスタリング（KMeans/GMM） | 使う | **失敗確定**（precision 46〜50%、ほぼチャンス） |

Method A に補助的な「手作り特徴量分類器」（`module/track_classifier.py`、
6 特徴量ロジスティック回帰）があり、③と④の間のノイズ除去に使える。
Method C の疑似教師データ生成にも使っている。

---

## 2. 直近で分かった重要なこと（優先度順）

### 2-1. CNN（Method C）の過去の比較結果は統計的に無効

seed=1,2,3 で同一データ・同一コードを学習した結果、
**precision が幅 6.6pt、recall が幅 10.9pt ばらつく**（sd それぞれ
3.3pt / 5.5pt）。7/23〜7/24 に報告した「grain_radius 修正の効果」
「pos_weight の効果」はいずれもこの幅の内側で、**差があったとは
言えない**。

原因は検証セットが小さすぎること（実ラベル 4 タイルのうち 1 枚＝
55 クロップのみ）。最良 val_loss のエポックが seed ごとに 1/4/7 と
ばらつき、チェックポイント選択が実質ランダムに precision/recall
トレードオフ曲線上の別の点を拾っている。

→ **今後 CNN 側で改善を主張するには最低 3 seed の平均±sd が必要**。
詳細は `e07-ml-binary-segmentation/analysis-note.md` 2026-07-27 (2)。

### 2-2. 「本番パラメータ」の定義が 5 箇所に分散していた

`config/default.yaml` の `viewer` ブロックが**真の本番設定**
（`analyze_cli.py`／`app.py` が読む）。`finder.py` の Python 既定値は
別物で、両者がずれていた。修正済みの 2 件：

| パラメータ | 旧 | 新 | 効果 |
|---|---|---|---|
| `hough_mg` | 5（yaml）/ 4（finder.py） | **40** | 本物飛跡ピクセルの recall 45.8%→92.7% |
| `grain_radius` | 15（yaml）/ 10（finder.py） | **15** | 分類器 LOTO precision 83.4%→85.5%（recall 不変） |

**まだ残っている不一致**: `finder.py` の `thr=20/ml=25` vs yaml の
`thr=35/ml=30`。ただし thr/ml は recall にほぼ影響しない
（スイープ済み、幅 2pt 以内）ので優先度は低い。

→ **教訓: `finder.py` の定数を「本番値」と思い込まないこと。
必ず `config/default.yaml` を確認する。**

### 2-3. Method A の④（反応点検出）は recall だけ良く precision が壊滅的

`specials_x20`（既知 ΛΛ ハイパー核 9 事象）のテストは 35/35 通過するが、
これは **recall のみの検証**。実際には 1 タイルあたり 196〜380 個の
vertex 候補が出て、正解は n_tracks 順で 7〜25 位に埋もれる。
`_MIN_N_TRACKS=5` だけでは判別力が全く足りない。

→ 物理ベースの最終フィルタ（dE/dx 粒子識別、MC による頂点運動学
整合性）は「あれば良い追加」ではなく**必須**、と定量的に裏付け済み。

---

## 3. kekcc 環境の調査結果（2026-07-27 時点）

login node = `cw02.cc.kek.jp`（`hayashu@login.cc.kek.jp`）

### 使えるもの

- **E07 実データ**: `/group/had/sks/E07/tohoku/fullscan/{E07,E373}/`
  （macOS 側はこれを NFS マウント→不安定だったため
  `~/out-of-sync/e07/fullscan/` にローカルコピー済み）
- **pip --user**: 動く（pip 25.1.1 / Python 3.9.21）
- `/opt/anaconda3/bin/python` あり

### 足りないもの（要対応）

| 項目 | 状況 |
|---|---|
| **torch** | system python3.9 にも /opt/anaconda3 にも**無し** |
| **sklearn, cv2** | 同上、**無し** |
| **GPU** | login node に nvidia デバイス無し。計算ノートの GPU 有無は未確認 |
| **バッチシステム** | `bsub`/`sbatch`/`qsub` いずれも PATH に**無し**。`/usr/share/lsf*` も無し |
| **module コマンド** | 無し（ただし `/opt/Modules` ディレクトリは存在） |

**重要**: リポジトリには LSF 前提のスクリプト
（`scripts/kekcc_job.sh`、`module/pipeline/cli_submit_kekcc.py`、
`bsub -q s` を使う）があるが、**login node から bsub が見えない**。
kekcc がバッチシステムを移行したか、環境設定が必要か、
計算ノードでのみ使えるのか、**要確認**。これが分からないと
「重い計算を kekcc に投げる」計画自体が成立しない。

### リポジトリの状態

- kekcc: `~/work/e07/fullscan`（**名前が `e07-fullscan` ではない**）、
  HEAD = `baa81a2 "minor change."`
- macOS: `~/work/e07/e07-fullscan`、HEAD = `5286d28`

**kekcc 側は大幅に古い**。ここ 2 週間の作業（ラベリング UI、
track_classifier、Hough パラメータ修正、疑似ラベル生成スクリプト）が
一切入っていない。`git pull` が必要。

`e07-ml-binary-segmentation`（Method C）は kekcc に**未クローン**。

---

## 4. kekcc でやる価値がある作業の候補

1. **CNN の LOTO 評価**（Method C の評価手法を直す）
   実ラベル 4 タイルで leave-one-tile-out × 3 seed = 12 回学習。
   macOS では 1 回約 2 時間なので 24 時間規模。GPU があれば大幅短縮。
   → **torch のインストールと GPU/バッチの有無確認が前提**

2. **Method A を実 fullscan 全域に流す**
   2025 タイル × 約 100 スライス。④の候補が膨大に出ることは
   分かっているので、まず数タイルで見立てを取るのが妥当。
   → torch 不要、sklearn/cv2 は必要

3. **Method B（MATLAB）** は当面使わない方針（ユーザー判断）

---

## 5. 引き継ぎ時の注意

- **`analysis-note.md` が一次資料**（各リポジトリ、逆時系列）。
  このメモは要約なので、細部は必ず原典を見ること。
- **`discussion.md` / `discussion_ja.md`** はエージェント間調整用の
  追記専用ログ。作業開始前・共有ファイル編集前・報告前に確認する
  （`CLAUDE.md` の指示）。
- **重い I/O を iCloud Drive 上に置かない**。macOS 側で `~/work` が
  iCloud へのシンボリックリンクであることに起因して、学習が 22 時間
  ハングした（`STAT=UN`、CPU 時間 11 分のみ）。
  → `data/`・`results/` を `~/out-of-sync/e07-ml/` に退避して解決。
- **単一実行の数値で改善を主張しない**（2-1 の教訓）。
- コミットは明示的に依頼されたときのみ。`Co-Authored-By` は付けない。
