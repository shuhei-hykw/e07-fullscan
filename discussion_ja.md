# 議論ログ

Codex と Claude Code が同じリポジトリで並行作業するための共有調整
メモ。追記専用で運用する。


**過去ログ**: 2026-07-11 より前のエントリは `discussion_archive_2026H1_ja.md` に移動（2026-07-27、内容無改変）。

## 2026-07-11 13:30 JST — Claude: 作業意図 — MATLAB エクスポート試作の commit & push

ユーザーが 2026-06-23 試作のコミットを承認。作業内容：ANALYSIS.md /
ANALYSIS_ja.md に 2026-07-11 の ToDo 整理エントリを追記した上で、一式
（`module/matlab_export.py`, `run.py`, README.md, ANALYSIS.md,
ANALYSIS_ja.md, discussion.md, discussion_ja.md）を 1 つの feature コミット
として `main` に載せ、`origin/main` へ push。ジョブ起動・データ出力はなし。
試作 `.mat` はリポジトリ外のまま。所有ファイルは 2026-06-23 エントリから
変更なし。push 後に Notion image-pre-processing DB へ 2026-07-11 の行を追加
する。

## 2026-07-11 13:58 JST — Claude (macOS): 完了 — macbook 上でリポジトリ検証、移植性修正2件

リポジトリを macbook（`~/work/e07/e07-fullscan`、iCloud 同期）へ移設。kekcc の
HEAD `baa81a2` と同一ツリー。`.venv`（Python 3.14, OpenCV 5.0）を構築し、
テストを全実行: 非 slow 52 件 + slow 35 件（`E07_SPECIALS_DIR` をローカルの
`../specials_x20` に向けて実行）= 87/87 通過。以下の2件の修正が必要だった
（未コミット）:

- `pyproject.toml`: `build-backend` が存在しない
  `setuptools.backends.legacy:build` になっており editable install が失敗。
  `setuptools.build_meta` に修正。
- `module/pipeline/finder.py`: OpenCV 5 では `HoughLinesP` の返り値が
  `(N, 1, 4)` ではなく `(N, 4)`。`lines[:, 0]` を `lines.reshape(-1, 4)` に
  変更（OpenCV 4/5 両対応）。

所有ファイル: `pyproject.toml`, `module/pipeline/finder.py`。ジョブ起動・
データ出力なし。補足: `fullscan-image` symlink は kekcc の絶対パス
`/group/had/sks/E07/tohoku/fullscan` を指したまま。sshfs マウント先
`~/mnt/kek_e07`（FUSE-T）は準備済みだが未マウント。

## 2026-07-11 14:09 JST — Claude (macOS): 完了 — pyenv + requirements.txt へ移行、エージェント設定ファイルを git 管理外へ

ユーザー指示による変更:

- `AGENTS.md` / `CLAUDE.md` を git 管理から除外（`git rm --cached`）し
  `.gitignore` に追加（ファイル自体はローカルに残る）。`.python-version` も
  ignore。
- `requirements.txt` を新規作成（core + flask + pytest/ruff）。
  `pyproject.toml` はツール設定（pytest マーカー、ruff）のみに縮小。
  `[project]` のパッケージ記述と `e07analyze`/`e07merge`/`e07view` の
  console scripts は削除 — grep で過去の日誌以外に使用箇所がないことを確認
  済み。`run.py` は `python -m module.<target>` に委譲するため影響なし。
- Python は pyenv 管理に移行: 3.14.6 をビルドし `pyenv local` で設定
  （`.python-version`、未追跡）。旧 `.venv` は削除。`module` はリポジトリ
  ルートから import されるため editable install は不要。
- README の Setup / Tests 節を更新（pyenv 手順、`E07_SPECIALS_DIR` の注記）。
- 検証: pyenv の Python で非 slow 52/52 通過。slow スイートは実行中、結果は
  追記予定。

所有ファイル: `.gitignore`, `requirements.txt`, `pyproject.toml`, `README.md`。

## 2026-07-11 14:20 JST — Claude (macOS): 完了 — メモを analysis-note.md に統一、Notion 廃止

ユーザー判断による変更:

- メモは単一ファイル `analysis-note.md`（日本語）に統一。
  `ANALYSIS.md` / `ANALYSIS_ja.md` は削除（git は ANALYSIS_ja.md からの
  リネームとして検出、履歴は追跡可能）。日付エントリ全 43 件を移行。
- エントリは逆時系列（最新が上）で時刻入り:
  `## YYYY-MM-DD HH:MM JST — <タイトル>` を `## 開発ログ（最新が上）`
  見出しの直下に挿入する運用。既存の日付のみ見出しはそのまま
  （本日の 3 件のみコミット時刻・作業ログから時刻を補完）。
- リファレンス・未解決課題セクションはファイル上部に維持。
- Notion（image-pre-processing DB）は廃止。CLAUDE.md / AGENTS.md の
  該当ルールを書き換え、README の参照先も analysis-note.md に変更。
- 併せて slow スイートを pyenv の Python で再検証 — 35/35 通過（約 8.5 分）。
  pyenv 移行の検証完了（52 + 35 = 87/87）。

所有ファイル: `analysis-note.md`, `README.md`, `CLAUDE.md`, `AGENTS.md`。
Codex への注記: ANALYSIS.md / ANALYSIS_ja.md は存在しない。作業記憶の再構築
時は `analysis-note.md` を読むこと。

## 2026-07-11 15:29 JST — Claude (macOS): 完了 — 実データ初の MATLAB テスト: detectlseg がスケールしない

実データを初めてグラフ検出器ステージ2に投入（macbook、MATLAB R2026a、
KISO specials タイル）。エクスポート（12.36M ヒット）と mabiki(pl,3)
（7.7 秒 → 2.46M 点）は問題なし。ボトルネックは detectlseg_smallregion:
領域ごと ~N²、2,991 点 → 291 秒、1 万点超の領域が 117/256、外挿で
1 タイル**約 392 時間**。1 時間で中断（13/256 領域）。多重度カットは
無効（実データは 3×3 ブロックが飽和、nn=9 が最大ビン）。試算では
n≥40+mabiki3 → 約 5.7 h、n≥40+mabiki6 → 約 1.8 h だが、輝度カットは
ヒットの ~10% しか残らず efficiency 最優先方針と衝突。詳細は
analysis-note.md（2026-07-11 15:29 エントリ）。次ステップ候補も同所に
記載、ユーザーの方針待ち。所有: results/matlab/*（gitignore 済み）、
analysis-note.md。

## 2026-07-11 18:29 JST — Claude (macOS): 完了 — 重心化エクスポートで detectlseg が実用時間に（KISO 全域完走）

ユーザー方針（MATLAB の .m ファイルは変更しない。前段の前処理を再考する）
に従って対応。第1回テストの約392時間の元凶は、生ピクセル方式のエクスポート
が二値マスクの1ピクセルごとに1ヒットを生成していたこと。1つのグレイン
ブロブ（数十px）が数十個の重複ヒットになっており、detect_tracks.m が
想定する「1 hit = 1 粒子」という意味とも乖離していた。

`module/matlab_export.py` に `export_hits_centroid()` を追加（CLI の
デフォルトに変更。`--mode pixel` で旧方式も比較用に選択可）: スライスごと
の connected component の重心を1ヒットとする方式。輝度カットと違いどの
ヒットも捨てないため、efficiency 最優先方針とも衝突しない。

KISO での効果: 1,236万 → 10.1万ヒット（122倍減）、最大領域の点数
26,962 → 838（32倍減）。全256領域の detectlseg_smallregion を初めて
最後まで完走: 9,067.5秒（2.52時間）、検出セグメント24,799件。事前の
N³ 外挿（2.48時間）とほぼ一致。既知 vertex 領域（region 137、
vx=1096/vy=1028/z_slice=10、tests/specials_gt.json）から半径80px・
z±8スライス以内に113セグメントが存在し、空でも無秩序でもない妥当な
トラック密度を確認。ただし detectbunki（分岐点／vertex 再構成）は
未実行で、既知の ΛΛ vertex がエンドツーエンドで再構成できるかはまだ
確認できていない。

詳細と次の一手候補は analysis-note.md（2026-07-11 18:29 エントリ）。
matlab_export.py 変更後、高速テスト再検証済み（52/52）。所有ファイル:
module/matlab_export.py, analysis-note.md, results/matlab/*（gitignore
済み、未コミット）。MATLAB（.m）ファイルには一切手を入れていない。

## 2026-07-11 20:14 JST — Claude (macOS): 完了 — 重心の輝度加重化 + Web ビューアでの生画像→MATLAB点群パイプライン可視化

前回コミット（9239c11）への2件のフォローアップ:

1. `module/matlab_export.py`: `weighted_centroids(binary, intensity)` を
   追加。形状のみの `cv2.moments(cnt)` をやめ、各ブロブの bounding box を
   fog除去後画像でマスク・重み付けしてから `cv2.moments` を適用する
   輝度加重重心に変更。KISO slice10 で検証: 幾何重心からの平均シフト
   0.49px、最大シフト14.98px（面積3075のブロブ）——大きい/歪んだ
   グレインクラスタほどシフトが大きい、想定通りの結果。
   `export_hits_centroid()` をこれに切替。ヒット数・所要時間は不変
   （101,479ヒット、約5秒）。
2. `module/server/app.py`: `/view/` の Processing Pipeline に
   「Grain Centroids (MATLAB)」ステップを追加（Noise Removal と
   Hough Lines の間）。`_process()` を再構成し、閾値処理後も
   fog除去後のグレースケール画像を保持するようにした（従来は
   `current` を上書きしていたため背景として使えなかった）。重心を
   黄色い円（ブロブ半径）+ 赤い点（輝度加重重心）でオーバーレイ表示。

KISO 既知vertex（vx=1096, vy=1028, z_slice=10、tests/specials_gt.json）
での目視確認: ローカルビューア（`python -m module.server specials_x20
--port 8123`）から4段階（raw/fog/binary/centroidオーバーレイ）を取得し
400×400pxでクロップ。fog除去後の画像でトラック様の複数の線がクロップ
中心付近でほぼ収束しており、既知vertex座標と一致。centroidオーバーレイ
でもその収束線に沿って重心が並んでおり、density削減がランダムな間引き
ではなく実際のトラック構造を保持していることを確認。4パネル比較を
Artifact として公開:
https://claude.ai/code/artifact/8f9a90a2-7186-41e2-992c-3e80fd078241

高速スイート再検証済み（52/52）。所有ファイル: module/matlab_export.py,
module/server/app.py, analysis-note.md。ローカルビューアは :8123 で
起動したまま（対話確認用）。

## 2026-07-11 21:03 JST — Claude (macOS): 完了 — 04パネルの解説とブロブ実形状表示への変更

ユーザーから「04の絵はどう見るか」「MATLAB側でクラスタリング済みでは
ないか」との質問。回答: MATLABは何もしていない。centroidモードの
テストでは `mabiki` を意図的にスキップしており、線分クラスタリングを
行う `detectlseg_smallregion` も今回のセッションでは未実行。04パネルの
グレイン単位への集約は全て `module/matlab_export.py` の Python側
`weighted_centroids()` によるもので、MATLAB処理前の段階。

見た目が紛らわしかった原因: オーバーレイがブロブごとに `√area` 比例の
円を描いていたため、vertex付近で複数トラックのグレインが融合した大きい
連結成分（面積3000px超）が目立ち、手動で引いたクラスタ境界のように
見えていた。

対応: `weighted_centroids()` が生の輪郭も返すよう拡張
（`(cx, cy, area, contour)` の4要素）。`module/server/app.py` の
`cent` ステップは面積比例の円ではなく、**実際のブロブ輪郭**（赤）＋
**重心位置の十字**（黄）を描画するよう変更。輪郭1つ⇔十字1つの対応が
視覚的に明確になり、トラック方向に沿って輪郭が伸びている様子も見える
ようになった。KISO既知vertexで再確認済み。Artifact（同一URL）を更新:
https://claude.ai/code/artifact/8f9a90a2-7186-41e2-992c-3e80fd078241

高速スイート再検証済み（52/52）。所有ファイル: module/matlab_export.py,
module/server/app.py, analysis-note.md。

## 2026-07-11 21:19 JST — Claude (macOS): 完了 -- connected-componentモードに致命的バグ（長いトラックが1点に潰れる）、固定グリッド方式へ全面置換

ユーザーからの一連の質問（「クラスタリングは不要では」「全ピクセル
そのまま渡すのは危険では」「二値化までで渡すのもダメか」）を受けて
実際の欠陥を発見。

発見: KISOに bounding-box 延長882px（面積わずか4845px、明らかに
1本の連続トラック）の connected component が存在。従来の
`weighted_centroids()`（connected-componentベース）はこれを1点に
集約しており、線・vertex 情報が完全に失われていた。延長100px超の
ブロブは1,123/101,479（約1.1%）で、稀なエッジケースではない。
Webビューアで実際に可視化して確認（1本の連続線に十字1つだけ）。

生ピクセルモードの非現実性を実測データによる2通りの独立な外挿で
再確認: 157点の頑健な対数回帰フィット（k=2.887）では全タイルで
約1.5万日、生ピクセルモード自身の実測2点による自己無矛盾フィット
（k=2.11）では約635日。フィット方法で桁が2つ違うが、どちらにしても
破滅的という結論は変わらない——生ピクセルでも二値マスクそのまま
（同じ `export_hits`/pixelモード）でも行き詰まる。

connected-componentクラスタリングを固定グリッドビニング
（`module/matlab_export.py` の `weighted_grid_hits`,
`export_hits_grid`）に置換: `cv2.findContours` 等の形状・連結性判定を
一切使わず、ピクセルを位置だけで30×30pxの固定セルに割り当て、
セルごとに輝度加重重心を1点出力。セルサイズは 10/15/20/25/30px の
スイープと detectlseg 時間の頑健なべき乗則フィットから30pxを選定:
130,364ヒット（旧connected-component方式の101,479よりやや多い）、
最大領域1,111点、検出時間見積 約6h（実測済み2.52hに近い）。KISOを
再エクスポートし、以前1点に潰れていた882px長のトラックが468点に
分割されていることを確認。Webビューアの「Grain Centroids」表示も
うっすらとしたグリッド線+十字（ブロブ輪郭は廃止、概念自体が
なくなったため）に変更。

実測での約6h見積もりを検証するため、全256領域の detectlseg 実行を
バックグラウンドで開始する。高速スイート再検証済み（52/52）。
所有ファイル: module/matlab_export.py, module/server/app.py,
analysis-note.md, results/matlab/*（gitignore済み）。

## 2026-07-12 02:53 JST — Claude (macOS): 完了 -- 固定グリッド方式のフルタイル実測が完了、約6h見積もりと一致

前エントリ（connected-component→固定グリッド切替）のフォローアップ。
グリッドモードのKISOエクスポート（130,364ヒット）で全256領域の
detectlseg_smallregion を実行: 19,802.2秒（5.50時間）、検出セグメント
30,179件——事前のべき乗則見積もり（約6.01h）とほぼ一致し、これまでの
外挿アプローチの妥当性が裏付けられた。connected-componentモードの
実測2.52hより遅いが、長いトラックの collapse バグ修正の代償として
受け入れられる範囲。

既知vertex（KISO vx=1096/vy=1028/z_slice=10）周辺チェック: 80px・
z±8スライス以内に81セグメント（旧connected-componentモードでは113件）
——同程度の密度で構造が保持されている。

現状: 今回の一連の調査を通じてMATLAB（.m）ファイルには一切手を入れて
おらず、修正は全て module/matlab_export.py（前段処理）側。推定392時間
（生ピクセル）から実測5.5時間/タイルまで改善し、同時に長いトラックの
情報を静かに破壊する正当性バグも修正した。次の課題: 全2025タイルへの
スケール（5.5h/タイルでは並列化・計算資源確保なしに非現実的）、
detectbunki を実行して既知vertexが実際にエンドツーエンドで再構成
できるかの確認。

高速スイート引き続き52/52（今回はエクスポート側変更なし、MATLABのみ
実行）。所有ファイル: analysis-note.md, results/matlab/*（gitignore済み）。

## 2026-07-12 15:25 JST — Claude (macOS): 完了 -- ハイブリッド（connected-component + 局所グリッド）方式に改良、視覚的に修正を確認

ユーザーによる用途の明確化: Python前処理 → MATLAB候補選出 →
スキャナー（人）選別 → 結果を教師データとしてフィードバック。MATLAB
は無変更、前段処理のみが対象範囲。

`detectlseg_smallregion.m` を読み込みユーザーに説明: 第1段階は全ペア
距離行列（pdist）→最小全域木を構築し、直線状になるまで枝を切る。
第2段階はSVDフィット+近傍点探索で線分を成長・統合・精緻化、収束まで
反復。`pdist` がN²ペアで支配的コスト、実測フィット（N^2.9程度）とも
整合（反復ループが追加のN²パスを重ねるため）。

ユーザーからHoughベースの再サンプリング提案（先にトラック方向を検出し
それに沿って点を残す）。per-slice `cv2.HoughLinesP` を試作: デフォルト
（z投影用）パラメータでは前景ピクセルの24-30%しかカバーせず、緩めると
77-83%まで改善するが1スライス5000本超の重複線分が出て、
`cluster_tracks`/`link_tracks` 相当の統合ロジックが必要になり複雑化
すると判明、今回は見送り。

代わりにシンプルな修正を採用: `weighted_grid_hits()` を
connected-componentでの分離（形状クラスタリングでなく単純な連結性
判定）→ 大きい成分だけ内部を固定グリッドで再分割、に変更。コストは
純グリッドとほぼ同じ（KISO: 133,183ヒット vs 130,364、最大領域1,201
vs 1,111）。視覚的に修正を確認: 1スライスで671組の近接するが別成分
のペアを検出、6-7倍拡大比較で旧グリッド方式（赤）の点が2つの別トラック
構造の間の空白に浮いており、ハイブリッド方式（黄）の点は常に実構造上
にあることを確認。

高速スイート52/52。KISO再エクスポート済み（133,183ヒット、4.3秒）。
全域detectlseg再検証（約5.5-6h）は密度がほぼ変わらないため未実行——
ユーザー判断待ち。所有ファイル: module/matlab_export.py,
analysis-note.md, results/matlab/*（gitignore済み）。

## 2026-07-12 17:25 JST — Claude (macOS): 完了 -- スケルトンベースの中心線抽出を実装、視覚的・定量的に検証

`integrate_smallregions` クラッシュとトラック幅の発見へのフォローアップ。
「MATLAB側のトラック検出を肩代わりしているのでは」という懸念は、これを
画像レベルの形状クリーンアップ（fog除去/Otsu/ノイズ除去と同カテゴリ）
と位置づけることで整理——トラック/vertexの物理的識別はMATLAB側に残す。

`requirements.txt` に `scikit-image`（`skimage.morphology.skeletonize`）
を追加。`weighted_grid_hits()` はセルサイズを超える connected component
を、セル分割前に1px幅の中心線（メディアル軸スケルトン）に細線化する
ように変更——ヒットの**位置**はスケルトンの輝度加重重心から、
**`n`**（密度指標）は元のブロブのセル内ピクセル数のまま維持。ヒット
総数は不変（133,183件、位置のみ変更）。

既知の882px長トラック（1つのconnected componentだけを正しく単離して
測定——バウンディングボックスでのフィルタは無関係な点を巻き込み
意味のない数字になる、と2度学んだ教訓）で定量検証: 局所（40px窓）
垂直半幅が、局所最大値平均8.12px/中央値6.63px/局所平均値平均2.24pxから、
それぞれ2.70/2.51/1.56に改善——約2.6-3倍の削減。
`detectlseg_smallregion` のTH=1.5-2pxには近づいたが完全には収まって
いない（グリッドセル分割自体が残差を生むため）。

2枚組の可視化（全長概観+6倍拡大詳細）を作成: 元のブロブ輪郭（青）、
スケルトン（シアン）、最終エクスポート点（黄十字）を重ね描き、幅の
collapse を直接視認可能に。既存Artifactに追記（同一URL）:
https://claude.ai/code/artifact/8f9a90a2-7186-41e2-992c-3e80fd078241

未検証: `integrate_smallregions` のクラッシュが実際に解消するかは
まだ未確認（5×5領域の局所テスト再実行が必要、約86分）。

高速スイート52/52。KISO再エクスポート済み（133,183ヒット、5.3秒）。
所有ファイル: module/matlab_export.py, requirements.txt,
analysis-note.md, results/matlab/*（gitignore済み）。

## 2026-07-12 18:44 JST — Claude (macOS): 進行中 -- ノイズ削減調査（3系統並行）、analysis-note.md 更新

前回コミット（スケルトン実装）以降の内容を analysis-note.md に反映:
長さ方向の間引き省略は不可と確認（フルスケルトン・間引きなしで
見積もり505日）、pdist高速化案は撤回（プロファイルで subfunc1/pdist
は全体の0.4%のみと判明、MATLABファイルは一切変更していない）、
`integrate_smallregions` の実クラッシュを確認（根本原因: トラック幅が
detectlsegのTH許容値の3-4倍）、スケルトン修正の定量改善（約2.6-3倍）
を記録。

今回新規: 「点数の66%が小さい孤立塊」問題への3つの古典的判別手法を
試行。伸長度（不発、面積との相関なし）・孤立度（不発、乳剤画像自体が
密で中央値21pxに何か構造がある）はどちらも分離力なし。Hough整合性は
成功: 検出直線から3px以上離れた塊は面積中央値20px、整合する塊は
114px。単純閾値では点数の28.6%を削減できるが、vertex近傍の
スポットチェックで面積114-173pxの塊も削除対象になってしまうことが
判明——面積<30pxを併用した保守版（18.8%削減）の方が安全で、可視化で
実信号（トラック線上の塊）を保護できていることを確認。

理研Kasagi氏のコード `binary_segmentation`（独立研究のため重み共有
不可）をローカルで発見・解析: `segmentation_models_pytorch` ベースの
U-Netによる二値セグメンテーション（グレースケール入力→トラック
マスク出力）——私たちの `fog_remove→otsu_binarize→remove_noise` の
学習ベース版。重み入手不可。

ユーザーが3系統並行を希望: (1) 保守版Hough整合性フィルタの検証・確定、
(2) 合成学習データの試作（実背景+簡略化幾何モデル+実測グレイン
テクスチャ、フルGeant4+GANは省略）、(3) 公開モデル"UCS"（SAMベース
汎用線状構造セグメンテーション）の転移学習可能性調査——バックグラウンド
エージェントに委任（GitHub: kylechuuuuu/UCS）、報告待ち。

次のTODO: (1)(2)を完了させ、(3)のエージェント報告を受け取り次第反映。
所有ファイル: analysis-note.md, results/matlab/*（gitignore済み、
各種試算スクリプト）、~/work/e07/binary_segmentation（外部リポジトリ、
参照のみ、e07-fullscanの一部ではない）。

## 2026-07-12 18:49 JST — Claude (macOS): 完了 -- 3系統並行調査の第1ラウンド完了（Houghフィルタ視覚検証・合成データprototype動作確認・UCS却下/micro-sam発見）

(1) 保守版Hough整合性フィルタ（非整合 AND 面積<30px）を既知vertex
周辺で可視化検証。積極版なら削除される「非整合だが面積≥30px」の塊が
複数、実際のトラック線上に乗っていることを確認——保守版
（18.8%削減）が実信号を守っていることを裏付け。積極版（28.6%削減）
より保守版を推奨、ただし実際のdetectlseg再実行での検証は未実施。

(2) コピー&ペースト方式の合成トラックprototypeが動作: 実データの
孤立小ブロブから収穫したグレインパッチを、実背景上に生成した直線
パスに沿って貼り付け、合成vertexに収束させる。視覚的に自然、GAN
ドメイン変換を完全に回避（全ピクセルが実データのため）。課題:
グレイン間隔（8px）は粗い推定、トラックは直線のみ（湾曲未
モデル化）、背景に実際の（ラベルなしの）本物トラックが写り込む
リスク。

(3) バックグラウンドエージェントによるUCS調査完了: **非推奨**
（ファインチューン済み重み未公開——7ヶ月間未対応のHuggingFace公開
依頼issueが証拠、LICENSEファイルなし、著者個人サーバパスが
ハードコード）。代替として **micro-sam**
（computational-cell-analytics/micro-sam、Nature Methods 2024）を
発見——顕微鏡画像専用のSAM派生、学習済み重み公開済み、小規模
データでのfine-tuningチュートリアルも整備済み。次点で vesselFM
（3D血管、CVPR25、非商用ライセンス）も記録。

Artifactを更新（同一URL、新規2パネル追加）:
https://claude.ai/code/artifact/8f9a90a2-7186-41e2-992c-3e80fd078241

次のTODO: (1) 保守版フィルタでの実際のdetectlseg再実行——主眼は
点数Nではなくセグメント数M（プロファイルで判明した真のボトル
ネック）への影響、(2) 合成データのグレイン間隔・背景選定の精緻化、
(3) micro-samの実際のセットアップとエマルジョン画像でのfine-tuning
実現性の調査。所有ファイル: analysis-note.md, results/matlab/*
（gitignore済み）。

## 2026-07-12 19:06 JST — Claude (macOS): 進行中 -- Houghノイズフィルタをmodule実装、実測MATLAB検証実行中、合成データ較正完了、micro-sam却下

`module/matlab_export.py`: `remove_unaligned_noise()` を実装し
`export_hits_grid()` に組み込み（denoise=Trueがデフォルト、
`--no-denoise` CLIフラグ追加）。KISO再エクスポート: 108,671ヒット
（旧133,183、-18.4%、事前試算と一致）。高速スイート52/52。

前回クラッシュした5×5局所テスト（`test_detectbunki_local.m`）を
denoise版データで再実行開始（バックグラウンド、約86分見込み）。
序盤2/25領域で、点数削減率を大きく上回る処理時間削減を確認:
row7/col7が930点/232セグメント/165.9秒→732点/175セグメント/68.1秒
（点数-21%、セグメント-25%、時間**-59%**）。プロファイルで判明した
「コストはセグメント数Mに比例」という知見と整合——ノイズ除去が
不釣り合いにMを減らしている可能性。`integrate_smallregions` の
クラッシュ解消有無は全完了後に判明。

合成トラックprototype: 参照トラック（882px）の輝度プロファイルに
ピーク検出を適用しグレイン間隔を実測——中央値9.00px、平均9.49px
（110ピーク）、以前の仮値8.0pxとほぼ一致。9.0pxを正式採用し、
各トラックに軽微な角度ドリフト（curvature=1.5°/グレイン、緩い
多重散乱を模した湾曲）を追加。

バックグラウンドエージェントによるmicro-sam調査完了: **こちらも
非推奨**、ただしUCSとは異なる理由——重み自体は公開済み（Zenodo、
MITライセンス、Apple Silicon MPS対応確認済み）だが、**タスク設計が
根本的にミスマッチ**。離散オブジェクト（細胞・核・オルガネラ）の
インスタンス分割用訓練であり、連結した線状構造の密な二値分割とは
性質が異なる。AISデコーダのforegroundチャンネル流用は技術的には
可能だが線状構造での実績なし、SAMの計算コストに見合わない。
UCS・micro-sam両調査から収束した推奨: 大型基盤モデルを探すより、
Kasagi氏も使っていた `segmentation_models_pytorch`（公式ライブラリ）
でImageNet事前学習エンコーダから軽量U-Netを自前データで学習する
方が現実的——系統(2)の合成データ生成と自然に合流。

次のTODO: denoise版局所テストの完走待ち、合成データセットの
規模拡大（数百〜数千枚）、`segmentation_models_pytorch` U-Netの
学習試作。所有ファイル: module/matlab_export.py, analysis-note.md,
results/matlab/*（gitignore済み）。

## 2026-07-12 19:57 JST — Claude (macOS): 完了 -- denoise版局所テスト完走: detectlsegは大幅高速化、integrate_smallregionsは同一クラッシュ

denoise版エクスポートでの25領域局所テストが完走。
detectlseg_smallregion: 3240.6秒/4840セグメント（旧skeleton-only版:
5153.3秒/5768セグメント）——時間-37.1%、セグメント-16.1%。プロファイル
由来の仮説（コストは点数Nよりセグメント数Mに強く効く）を方向性として
裏付け：ノイズ除去は点数・セグメント数の削減率以上に処理時間を
削減した。

**しかし `integrate_smallregions` は前回と全く同一のエラーで
再クラッシュ**（`pixellist2poly>subfunc2` 行136、空の点群への
インデックスアクセス）——スタックトレース・根本原因とも同一。前段
（Python側）の密度・品質改善だけでこのクラッシュが間接的に解消される
という仮説は**誤りだった**。`resamplingpoly`/`pixellist2poly` 側の、
断片化した線分から実体のない折れ線候補が生成されうる、再現性のある
ロジック上の欠陥である可能性が高く、断片化がある限り入力の質に
関わらず再現すると考えられる。

判断が必要な分岐点: 前段（Python）側の改善はここでほぼ限界。
選択肢: (a) `pixellist2poly` に最小限の防御的ガード（空の点群なら
早期return等）をMATLAB側に1箇所だけ加える、(b)
`integrate_smallregions`/`detectbunki` を今は使わず
`detectlseg_smallregion` の出力（線分候補）をスキャナー選別向けの
成果物とする設計に変更、(c) その他——ユーザーの判断待ち。

所有ファイル: analysis-note.md, results/matlab/*（gitignore済み）。

## 2026-07-12 20:57 JST — Claude (macOS): 進行中 -- MATLAB側に最小限の修正を適用（ユーザー承認）、実測検証を再実行中

ユーザーが前回の分岐点で選択肢1（最小限の防御的ガード）を選択。実装中
の調査で、当初提案した修正箇所では不十分と判明し、変更した:

- `pixellist2poly()` の呼び出し元は1箇所のみ（grep確認済み）:
  `integrate_smallregions.m` 内の `resamplingpoly`。
- 最初の試み（`pixellist2poly` 内で空データなら
  `zeros(0,Dim)` を早期return）は不十分と判明: 呼び出し元
  `integrate_smallregions.m` 107-110行目に、長さ0チェックより**前**の
  無条件インデックスアクセス `lseg(:,:,i) = polylines{i}([1 end],:)`
  があり、`polylines{i}` が空だとそこでクラッシュが単に移動するだけ
  だった。この試みは破棄（`pixellist2poly.m` を編集前のバックアップと
  バイト単位で完全一致するよう復元、diff確認済み）。
- 実際の修正: `resamplingpoly` 内、`pixellist2poly` 呼び出し直前に
  ガードを追加。`x1`（近傍の実点群）が空なら呼び出しをスキップし、
  `polylines{i}` の座標データはそのまま残し（下流の無条件
  インデックスアクセスに対して安全）、`lpoly2(i) = 0` だけ設定。
  これは新しい規約ではなく、`integrate_smallregions.m` 118行目に
  既にある「長さ0の線分は飛ばす」処理が元々想定していた挙動を、
  `pixellist2poly` 側が正しく返せていなかっただけ。

編集した両ファイル（`~/work/e07/matlab` はgit管理外）は編集前に
`.orig-20260712` サフィックスでバックアップ済み。MATLAB `checkcode`
で検証済み（既存のスタイル警告のみ、パースエラーなし）。

同じ5×5局所テストをバックグラウンドで再実行中（約50-90分、
detectlsegからやり直しが必要）。今後の再テスト高速化のため、
`lseg` の中間チェックポイント保存もテストスクリプトに追加。

所有ファイル: analysis-note.md, results/matlab/test_detectbunki_local.m,
~/work/e07/matlab/{pixellist2poly.m,integrate_smallregions.m}（外部、
e07-fullscanのgitリポジトリ外）。

## 2026-07-12 21:52 JST — Claude (macOS): 完了 -- MATLAB修正が成功。初のフルパイプライン完走、既知vertex近傍で有望な分岐候補を検出

`resamplingpoly` へのガード適用後、同じ5×5局所テストを再実行。
`integrate_smallregions` がクラッシュせず完走（8.0秒、2,381折れ線）
——今回の調査で初めてこのステップを実データで突破。`detectbunki`
も完走（2.0秒、1,815分岐グループ、うち3本以上の折れ線を持つもの
107件）。

既知KISO vertex（vx=1096/vy=1028/z_slice=10）から80px以内の分岐
グループ: group 1（21本、34.8px）、group 5（10本、14.5px）、
group 12（7本、29.6px）、group 31（5本、20.8px）、group 41（4本、
44.0px）、group 98（3本、14.5px）。group 1・5は
`specials_gt.json` のクリック精度（±50-100px）・テスト許容誤差
（±200px）の範囲内に十分収まる。

過大評価を避けるための注意点: 1つの局所領域のみのテストでタイル
全体での再現性は未検証、group 1/5の実際の折れ線がKISOの本物の
3トラックに対応するかは未確認（目視確認が必要）、「3本以上」の
表示条件は自分で設定した閾値であり全1,815グループを見たわけでは
ない。

次のTODO: group 1/5の実際の折れ線ジオメトリを可視化し既知トラック
と照合、問題なければより広い/全タイル規模の再現性確認へ。所有
ファイル: analysis-note.md,
results/matlab/test_detectbunki_local.m（チェックポイント保存追加）、
~/work/e07/matlab/{pixellist2poly.m,integrate_smallregions.m}（外部）。

## 2026-07-12 21:58 JST — Claude (macOS): 完了 -- Group1/5のポリラインを可視化: きれいな収束ではなく密集した塊、スキャナー選別候補として妥当

チェックポイントから高速再実行（`export_vertex_groups.m`、
detectlsegスキップ、10秒未満）でGroup1/5の実座標を取得し、既知
vertex周辺画像に重ねて可視化。正直な所見: 教科書的な3本収束では
なく、Group1（橙）は多数の短い折れ線が交差する密集塊、Group5
（黄）はvertexから複数方向に線が伸び緩やかに整合するが単純では
ない。

ユーザー自身の設計（MATLAB出力→スキャナー選別向け候補、完全
自動解決ではない）に照らして適切に位置づけ: この「乱雑だが収束
している」構造は失敗ではなく、人間選別に回すべき妥当な候補。
Artifactに追加（同一URL）。

現状: 1局所領域・1イベントでの単発成功。タイル全体・他イベントでの
再現は未検証。次の自然なステップは他の既知イベント（IBUKI,
IRRAWADY, NAGARA、いずれもn_clicks≥2）やより広い領域での再実行で
一般性を確認すること。

## 2026-07-14 01:05 JST — Claude (macOS): 完了 -- 公開済みサマリー
Artifact 2件の古い/低品質な画像を修正（パネル04+他2枚）

ユーザーから「パネル04（グリッド化後の点群）は全くだめ、スケルトン
（シアン）画像が一番綺麗」との指摘。原因は2つ: (1)
`kiso_cent_vertex_crop.datauri`の生成時刻が2026-07-12 14:37で、
スケルトン化コミット（`cca63da`、17:25頃）にもHough整合ノイズ除去
コミット（`da3d5a8`、19:06頃）にも先行しており、Artifactは既に
置き換え済みの素グリッド画像を表示し続けていた。(2)
既存の`cv2.drawMarker`描画はアンチエイリアスが無く、ユーザーが
高評価したmatplotlib製のスケルトン画像と見た目の差があった。

対応: `results/matlab/regen_panels.py`（新規、results/配下で
gitignore対象）を作成し、現行パイプライン（`weighted_grid_hits`+
`remove_unaligned_noise`、cell=30px）の実データから3枚を
matplotlibで再生成: パネル04（`kiso_cent_vertex_crop`）、ノイズ
フィルタ確認図（`filter_vertex_vis`）、detectbunki分岐グループ図
（`vertex_groups_overlay`、`vertex_groups_export.mat`由来）。いずれも
スケルトン画像と同じシアン`#5fd0c4`系配色に統一。両Artifact
（`kiso_vertex_pipeline_qa`、`e07_summary.html`）を同一URLで再公開。
パイプラインのコード自体に変更は無く、古い/低品質な可視化資産のみ
差し替え。

教訓: Artifactを更新する際、使い回しているdatauri画像の生成時刻を
パイプライン変更コミットと突き合わせていなかった。今後、可視化を
差し替えたら、同じ資産名を参照している全Artifactパネルの鮮度を
棚卸しする。今回の所有ファイル: analysis-note.md,
results/matlab/regen_panels.py（新規、gitignore対象）、
scratchpad側 build_gallery.py / build_summary.py（HTML再生成のみ、
ロジック変更なし）。

## 2026-07-15 13:40 JST — Claude (macOS): 新規リポジトリ
`~/work/e07/e07-binary-segmentation`（e07-fullscanと同階層の
兄弟リポジトリ）を作成、進行中。学習ベースのtrack/fog二値分割
モデル（古典フィルタが全滅したための次の一手、詳細は
analysis-note.mdの2026-07-15エントリ）。e07-fullscanの
`module.reader`/`module.preprocess`をパス参照で再利用（複製せず）。
副作用として、このMac環境のpyenv 3.14.6にtorch/
segmentation-models-pytorch/torchvision等をインストール済み——
e07-fullscan側からも同じpython環境なので見える点に注意。
e07-fullscan側のファイルへの変更は無し（analysis-note.mdへの追記
のみ）。まだgit未コミット（ユーザー確認待ち）。

## 2026-07-15 14:30 JST — Claude (macOS): `fullscan-image`
シンボリックリンクの向き先を変更（`/group/...` → `~/mnt/
e07-fullscan`）、本物のE07全面探査データをread-onlyでマウント

KISOがE373乾板（specials_x20全体もおそらく同様）でありE07とは
背景密度が異なる（実測で前景密度が約1.8〜2倍違う、詳細は
analysis-note.md参照）とユーザーから訂正を受け、KEKのE07全面探査
データを`sshfs ... ~/mnt/e07-fullscan -o ro`でマウント。
`e07-fullscan/fullscan-image`シンボリックリンクはこの新しい
マウント先を指すよう更新済み（以前の`/group/...`は存在しない
パスだった）。`/group`直下への新規sudoディレクトリ作成は
自動許可の対象外でブロックされたため、ホーム配下のマウント先に
変更した経緯あり。

このリポジトリ内のコード変更は無し（シンボリックリンクの向き先
とanalysis-note.mdへの追記のみ）。他エージェントが`fullscan-image`
配下を参照するコードを書く場合、E07/E373両方が並んで存在する点に
注意（`fullscan-image/E07/...`と`fullscan-image/E373/...`）。

## 2026-07-19 08:00 JST — Claude (macOS): `specials_x20`検証結果を記録

`tests/test_specials.py`（既知9事象のΛΛハイパー核vertex検証、
`-m slow`）を再実行したところ全35テスト通過。docstringの古い
「ほとんど失敗する」という記述を更新（原因は2026-07-11の
OpenCV5 HoughLinesP形状バグ修正だった可能性が高いという仮説を
併記）。詳細はanalysis-note.md 2026-07-18(14)。
所有ファイル: tests/test_specials.py（docstringのみ）、
analysis-note.md。他ファイルへの変更なし。

## 2026-07-19 10:30 JST — Claude (macOS): `fullscan-image`シンボリック
リンクの構造を変更(fuse-t NFS再マウントへの対応)

以前のsshfsマウント(`~/mnt/e07-fullscan`)が切断されていたため、
ユーザーがfuse-t NFS経由で`~/mnt/kek_e07`に再マウント。この新しい
マウント先は直下が`MOD108/`(旧`fullscan-image/E07/`相当、E373
サイドカーなし)という構造で、以前の`fullscan-image -> ~/mnt/
e07-fullscan`(直下にE07/とE373/が並ぶ)とは階層が1段違う。
対応として`fullscan-image`を通常ディレクトリに変更し、その中に
`E07 -> ~/mnt/kek_e07`のシンボリックリンクを作成——コード側の
`fullscan-image/E07/...`という参照パスはそのまま動く。E373側は
未対応(現状使っていないため)。詳細はanalysis-note.md
2026-07-19 10:30。所有ファイル: fullscan-image/(シンボリック
リンク構造のみ)、analysis-note.md。

## 2026-07-22 JST — Claude (macOS): 本番Hough `max_gap`パラメータを
5→40に変更(`config/default.yaml`, `diag_common.py`)

`config/default.yaml`の`viewer.hough_mg`(`analyze_cli.py`のKEKCC
v6バッチ解析、`app.py`ビューワ既定値が参照)を5→40に変更。
`module/pipeline/diag_common.py`の`TRACK_CFG`(同yamlのミラー)も
同様に変更。理由: 512件の手動ラベル(true判定223件)をピクセルマスク
化して測定したところ、旧値(mg=5)は本物飛跡ピクセルの約54%を検出
し損ねていた(recall 45.8%)。mg=40でrecall 92.7%まで改善、かつ
「長さ>300pxかつ粒密度<0.02」で診断した偽ブリッジ(無関係な点を
誤って繋ぐ)の水準はmg=20/30と同程度に抑えられることを確認。
詳細はanalysis-note.md 2026-07-22(2)。`module/pipeline/finder.py`
の`_HOUGH_MG`も同日先に4→40へ変更済み(ただしこちらは
`thr=20/ml=25`という別のフォールバック値のまま、yaml側の
`thr=35/ml=30`とは不一致——未解決)。
高速テスト52件は変更後も全通過、`specials_x20`検証(-m slow)は
再実行中。所有ファイル: config/default.yaml, module/pipeline/
diag_common.py, module/pipeline/finder.py, analysis-note.md。

## 2026-07-27 JST — Claude (macOS): kekcc セッションへの引き継ぎメモ
`HANDOFF_kekcc.md` を作成

重い計算を kekcc へ移す方針が出たため、macOS セッション
(702bbb20-...) から kekcc セッション (d7a92435-...) への引き継ぎ
メモをリポジトリ直下に作成。内容: Method A/B/C/D の現状、直近の
重要な発見3件(CNN のシードばらつきによる過去比較の無効化、
本番パラメータ定義の5箇所分散問題、Method A の④が recall のみ
良く precision 壊滅的)、kekcc 環境の調査結果、kekcc でやる価値の
ある作業候補。

**kekcc 側で要対応と判明した点**:
- `~/work/e07/fullscan` (名前が `e07-fullscan` ではない) の HEAD が
  `baa81a2` と大幅に古い。ここ2週間の作業が未反映、`git pull` 必要。
- torch / sklearn / cv2 がいずれも未インストール
  (system python3.9 にも /opt/anaconda3 にも無し)。
- `bsub`/`sbatch`/`qsub` が login node の PATH に無く、
  `/usr/share/lsf*` も存在しない。リポジトリの LSF 前提スクリプト
  (`scripts/kekcc_job.sh`, `cli_submit_kekcc.py`) が現状動くか不明——
  バッチシステムの現況確認が最優先。
- `e07-ml-binary-segmentation` は kekcc に未クローン。

所有ファイル: HANDOFF_kekcc.md (新規)。他ファイルへの変更なし。

## 2026-07-27 JST — Claude (macOS): ドキュメント体制の変更3件
（`STATUS.md`新設、パラメータyaml一元化、調整ログのアーカイブ分離）

セッション間の引き継ぎコスト削減のため、ユーザー依頼で3件実施。

**1. `STATUS.md`を両リポジトリに新設**（上書き運用、追記しない）。
セッション開始時に最初に読むべき「現在の状態」。analysis-note.mdは
履歴として併存。両CLAUDE.mdに運用ルールを明記。

**2. `module/pipeline/finder.py`が`config/default.yaml`を読むよう変更**。
これまでハードコードでyamlとずれ、`hough_mg`・`grain_radius`で
2回検出性能を劣化させていた。最後まで残っていた不一致
（finder.py thr=20/ml=25 vs yaml thr=35/ml=30）も解消。
**他エージェントへの影響**: `find_tracks`をパラメータ明示せずに
呼ぶコードは検出結果が変わる（thr 20→35, ml 25→30）。
明示的に渡している呼び出し側（`analyze_cli.py`, `app.py`,
`labeling.py`, `track_classifier.py`, `diag_common.py`）は影響なし。

**3. `discussion.md`/`discussion_ja.md`の2026-07-11より前を
`discussion_archive_2026H1{,_ja}.md`へ内容無改変で分離**。
現行ファイルは657/703行に縮小、エントリ欠落ゼロを検証済み。
CLAUDE.mdの追記専用規約に例外条項（ユーザー明示依頼時のみ、
逐語アーカイブ）を追記。

所有ファイル: STATUS.md(新規、両リポジトリ), CLAUDE.md(両リポジトリ),
module/pipeline/finder.py, discussion{,_ja}.md,
discussion_archive_2026H1{,_ja}.md(新規), analysis-note.md。
高速テスト52件通過。`specials_x20`検証(-m slow)は実行中。

---

## 2026-07-27 20:10 JST — Claude (kekcc): 引き継ぎメモを実機検証 — 2点訂正

`HANDOFF_kekcc.md` を kekcc 実機（cw07）で照合。記載2点が誤りで、
新たなブロッカーが1点判明した。

**訂正1 — LSF は使える。** ノート最大のブロッカー（「bsub が PATH に
無い、これが分からないと計画自体が成立しない」）は誤り。
`/opt/lsf/10.1/.../bsub` が存在し LSF 10.1（cluster `centralcluster`）が
稼働。ノートは cw02 での調査なので login node 差か PATH の問題。
`cli_submit_kekcc --dry-run` も正常完走し queue `s` / 135 ジョブの
bsub コマンドを生成する。Method A の全域投入はすぐ実行可能。

**訂正2 — リポジトリは古くない。** `baa81a2` ではなく HEAD は `f2b77d4`、
origin/main と同期、tree クリーン。`~/work/e07/fullscan` は gpfs 実体への
シンボリックリンクで別クローンではない。
（`e07-ml-binary-segmentation` 未クローンは記載どおり。）

**新規ブロッカー — GPU が使えない。** `bqueues -l g` の結果、GPU queue は
三重に不可: `USERS: shogo kmura ce_ibm/` に hayashu が含まれない
（`bqueues -u hayashu` は `s l h p a` のみ）、STATUS が `Closed:Inact_A`、
唯一の GPU ホスト `ccg01` が `unavail`。よって候補1（CNN LOTO を kekcc へ）
の動機は大きく低下し、CPU 実行となる。使用可能 queue は全て MEMLIMIT 4 GB。
`h` が walltime 8日 / TASKLIMIT 12 なので CPU 学習は可能だが、
`torch.set_num_threads()` を 12 以下に制限すること（既定で 64 を認識）。

**環境変更（ユーザー承認済み）。** conda `myenv` に追加:
scikit-learn 1.6.1、scikit-image 0.24.0、torch 2.8.0+cpu、
torchvision 0.23.0+cpu。numpy は 1.26.4 に固定し conda 版 opencv 4.12.0 を
壊さないようにした。ノートの「torch/sklearn/cv2 無し」は `myenv` を
見落としたもの（cv2 は元からあった）。検証: 全インポート OK、
`pytest -m "not slow"` 52 passed / 35 deselected で従来ベースラインと一致。

変更ファイル: `analysis-note.md`（2026-07-27 エントリ）、本ログ、
`discussion.md`。コミットはしない（明示依頼時のみ、というノートの方針）。

---

## 2026-07-27 22:45 JST — Claude (kekcc): specials の訂正、rename、Method C 環境整備 — manual_labels 待ちで停止

**ユーザーによる重要な訂正。** `specials_x20/` の 13 中 **11 が E07** 乾板で
本物の反応点データ: D005, D013, IBUKI, IRRAWADY, MINO, T004, T004_3body,
T004_center, T011, T011_100, T011_200。E373 は KISO と NAGARA のみ（優先度
低）。`tests/specials_gt.json` の実測 9 事象のうち **7 事象が E07**。
これにより STATUS.md の制約 2 件（「specials は E373 なので最適化対象に
するな」「実 E07 に確認済み反応点は 1 件も無い」）は撤回。2026-07-15 の
前景密度 約1.8〜2倍 の実測は KISO(E373) と E07 全面探査データの比較で
あって、specials 全体の性質ではなかった。

**ディレクトリ rename。** ユーザー指示により kekcc の
`~/work/e07/fullscan` を `~/work/e07/e07-fullscan` へ rename、macOS と
名前を統一。これで `e07-binary-segmentation/src/paths.py`（兄弟を
`e07-fullscan` の名前で探す）も解決する。fast tests 52 passed。旧名の
参照は追記専用ログと `HANDOFF_kekcc.md` にのみ残るが、規約どおり未編集。

**STATUS.md を両リポジトリで更新**（CLAUDE.md に従い上書き）:
specials の E07/E373 内訳、撤回した制約、kekcc 環境（bsub 可 / GPU 不可 /
myenv の内容 / numpy 固定）、`results/` が 2026-05-14 で止まっている件、
本日実測した mg=40 のトラック数 52 倍の件。

**Method C が kekcc で動くようになった。** conda `myenv` に導入:
scikit-learn 1.6.1、scikit-image 0.24.0、torch 2.8.0+cpu、
torchvision 0.23.0+cpu、segmentation-models-pytorch 0.5.0、matplotlib。
`smp.Unet(resnet18, in_channels=1, classes=1)` の 320x320 forward と、
兄弟リポジトリの `module.reader` / `module.preprocess` の import を確認。
numpy は 1.26.4 に固定したまま（conda 版 opencv 4.12.0 保護）。

**macOS 側への依頼（ブロッカー）。** kekcc には学習データが無く、生成も
できない。`e07-binary-segmentation/{data,results}` は macOS ローカルへの
シンボリックリンクで、大元の `e07-fullscan/results/manual_labels/*.json`
（人手 512 セグメント判定）は `.gitignore` の `results/` により git に
乗らない。kekcc 側は空。疑似ラベル生成も
`scripts/generate_pseudo_labels.py` が実行時に
`build_training_set(LABELS_DIR)` で分類器を学習するため同様に不可。
人手判定は再生成不能。

依頼: `results/manual_labels/` を kekcc から見えるようにしてほしい。
`.gitignore` に例外を入れて commit するのが妥当（小さく、代替不能で、
両マシンで必要）。手動コピーでも可。

本セッションの所有ファイル: STATUS.md（両リポジトリ）、analysis-note.md、
discussion{,_ja}.md。コミットは未実施。

---

## 2026-07-28 01:05 JST — Claude (kekcc): 作業意図 — LOTO 学習の実行（Method C）

ワークサーバ cw07 で leave-one-tile-out 学習を開始する（LSF ではない:
1 run あたり約 1 GB で 4 GB 制限は無関係、かつ短時間で終わるため）。

入力（読み取りのみ）: `e07-fullscan/results/manual_labels/*.json`（4 タイル、
人手 512 判定）を、今夜方向プレーンを追加して再生成した
`e07-binary-segmentation/data/real_labels/*.npz` 経由で使用。
出力（新規、すべて ML リポジトリ内）:
`results/loto/{arm}_{tile}_s{seed}.pt` と `.log`。24 通り =
2 arm（binary のみ / binary+方向）× 4 検証タイル × 3 seed、各 50 epoch、
1 プロセス 4 スレッド。
本セッションの所有ファイル: `e07-binary-segmentation` 側 —
`src/real_label_dataset.py`, `src/real_dataset.py`, `src/train_real.py`,
`src/train.py`, `src/model_defaults.py`（新規）, `src/eval_segments.py`（新規）,
`scripts/run_loto.sh`（新規）, `STATUS.md`。`e07-fullscan` 側 — `STATUS.md`,
`analysis-note.md`, `discussion{,_ja}.md`。
`e07-fullscan/results/` へはラベル読み取り以外の書き込みをせず、LSF ジョブも投げない。

## 2026-07-28 02:10 JST — Claude (kekcc): 訂正 — ワークサーバは4コア上限。LOTO を LSF へ移す

01:05 の「cw07 で学習する」計画は誤りだったので撤回する。kekcc は CPU を
food う対話プロセスを cgroup `/user.slice/restricted_user` に入れ、その
`cpu.max` は `400000 100000` ＝ **合計4コア**（128コアのノード上でも）。
`nr_throttled` は数百万回に達している。学習は最初の2〜3エポックこそ
22秒だったが、その後 throttle が効いて約370秒に落ちた。その間マシンは
96% アイドル。24／12／6 並列のいずれでも同じ挙動で、これが「自分同士の
競合」に見えていた原因。

Method C 以外への影響: 本日記録した「Method A の全域再解析はワーク
サーバ 16 worker で約6.5時間」は throttle 前の測定で、実際は約4倍かかる。
ワークサーバは編集と短時間テスト用であり、本番計算用ではない。

同じ 24 run を LSF の queue `h` に配列ジョブとして投入する（pending 78 /
running 522 で最も空いている。`l` は 113k、`s` は 32k pending）。
メモリは学習ピークが約 1.3 GB で 4 GB 制限に十分収まる。入力は変更なし
（`results/manual_labels/*.json` → `data/real_labels/*.npz`）。出力も
変更なし（`e07-binary-segmentation/results/loto/{arm}_{tile}_s{seed}.{pt,log}`）
＋ LSF 標準出力を `e07-binary-segmentation/logs/loto/` に。
新規所有ファイル: `scripts/loto_job.sh`。ローカルの throttle された
途中結果は投入前に削除済み。

## 2026-07-28 05:00 JST — Claude (kekcc): 完了 — LOTO 完走、CNN は判別力ゼロ

LSF 配列ジョブ 54866034 完了: 24/24 成功、失敗なし。1 ジョブ 4 コアで
約 30 秒/epoch、ピークメモリ約 1.3 GB（制限 3.9 GB）、CPU 効率 96%。

**結果（4 fold × 3 seed 統合、n=1536 セグメント、基準率 43.6%）**:
binary のみ / binary+方向 のいずれも precision 43.9% [41.4, 46.4]、
recall 98.5〜99.0%。**precision はどの層でも基準率と一致**
（rank≤100: 70.3〜70.5% vs 基準 70.4%、rank>1000: 14.6〜15.4% vs 14.6%）。
AUC は 0.43〜0.56 なので閾値のずれではなく、スコアに情報が無い。

**原因を特定。** 学習済みモデルを実スライスに通すと**画像の 78.6% を
飛跡と判定**（binary arm は 97.5%）、確率は最小でも 0.34 で「飛跡でない」
と言える場所が無い。マスクは画素の 99% が `-1`（損失から除外）なので、
モデルが見る負例は junk と判定された Hough セグメント＝薄い線状物体だけ。
**何もない乳剤を一度も負例として見ていない**ため背景を棄却できない。
2026-07-18 の「未レビューを 0 にしない」判断は Hough **候補**については
正しいが、候補から遠い空白画素にまで適用したのが行き過ぎだった。

修正は小さく、Method C 側 STATUS.md の「次にやる候補」最上段に置いた:
全候補線分を膨張させ、その外側を 0 とし、LOTO を再実行して AUC が 0.5 から
動くか見る。動かなければ壁はデータ量（学習に使えるのは 3 タイル）。

方向ヘッドは binary を悪化も改善もさせず、少なくとも併設して安全なことは
確認できた。`extract_segments.py` は動作する（学習済みで方向一致度 0.950、
未学習 0.837）が、マスクが画像の大半を覆う現状では連結成分が融合して
2,890 px の「線分」が出るなど、出力は物理的に無意味。

作業はすべてディスクに保存済みだが **git には未コミット**。2 リポジトリに
レビュー待ちの変更がある。対象ファイルは 01:05 / 02:10 のエントリに加え、
ML 側の `src/extract_segments.py`, `src/dump_segments.py`,
`src/eval_segments.py`, `src/model_defaults.py`, `scripts/loto_job.sh`,
`README.md`, `STATUS.md`、fullscan 側の `analysis-note.md`, `STATUS.md`。

## 2026-07-28 05:25 JST — Claude (kekcc): 背景負例の修正を実装、LOTO 再実行中

05:00 に特定した原因への対策を実装。`real_label_dataset.py` が全 Hough
候補を 12px 幅で描き、その外側の画素を junk としてサンプリングする
(`_sample_background`、明示ラベル 1 画素あたり背景 2 画素、seed 固定)。
1 タイルのラベル被覆率は約 0.95% → 約 2.9% になった。

スモークテスト（8 epoch、検証タイル V00000011）で意図した変化を確認:

| | 飛跡と判定した面積 | 確率中央値 | 確率最小 | val_recall |
|---|---|---|---|---|
| 修正前 | スライスの 78.6% | 0.563 | 0.340 | 約99% |
| 修正後 | **14.3%** | **0.072** | **0.000** | 65〜70% |

ほぼ全部を飛跡と答える状態から、背景を明確に棄却するようになった。
val_loss も約 0.60 → 約 0.37 に改善。

同じ 24 通りの LOTO を LSF 配列ジョブ 55017237（queue h）で再実行中。
比較のため旧結果は `results/loto_nobg/` と `logs/loto_nobg/` に保存、
新しい結果は `results/loto/` と `logs/loto/` へ。旧 npz は
`data/real_labels_nobg/` に残した。完了後にセグメント単位評価を行う。

## 2026-07-28 07:40 JST — Claude (kekcc): 完了 — 背景修正は効いたが十分ではない（AUC 0.54 → 0.59）

LSF 配列ジョブ 55017237 完了。セグメント単位 LOTO、4 fold × 3 seed、
n=1536、基準率 43.6%:

| arm | precision | recall | 予測陽性率 | AUC | 修正前 |
|---|---|---|---|---|---|
| binary | 49.5% [46.0, 53.1] | 55.8% | 49.0% | 0.582 | 0.549 |
| orient | 48.6% [45.3, 52.0] | 61.0% | 54.6% | 0.597 | 0.539 |

**改善した点**: precision が基準率を有意に上回った（両 arm とも CI 下限が
43.6% を超える）。修正前は precision＝基準率ちょうどだった。予測陽性率は
97.7% → 49.0%、スライス上で飛跡と判定する面積は 78.6% → 14.3%、確率の
最小値も 0.340 → 0.000 になり、背景を明確に棄却するようになった。

**足りない点**: AUC 0.59 は偶然よりましというだけ。**層内では基準率との差が
有意でない**（上位100位帯 73.9% vs 基準率 70.4%、CI 下限 69.5）。よって
全体 AUC の一部は「上位帯と裾帯を見分けているだけ」の可能性が高い。
**主指標は層内 AUC にすること。**

方向 arm が binary をわずかに上回った（全体 0.597 vs 0.582、上位帯
0.593 vs 0.550）。CI 内なので断定はできないが、修正前のように区別
不能ではなくなり、害も無い。

`extract_segments.py` も改善: 線分 680 本（旧 144）、中央長 27.9px
（旧 15.8）、最大の融合成分 1,246px（旧 2,890）。ただし 680 本中 355 本が
交差/塊フラグ付きで、連結成分ベースの分割は依然弱い。方向場を使った
分割が次の自然な手。

残る壁はデータ量。学習に使えるのは 3 タイルだけで、過学習も未解消
（train_loss 0.026 vs val_loss 0.98）。次の一手は Method C 側 STATUS.md
の最上段＝ラベル追加で、E07 specials の反応点から放射する飛跡が
非循環な供給源になる。

git には未コミット。両リポジトリにレビュー待ちの変更あり。背景なしの
旧結果は `results/loto_nobg/`、`logs/loto_nobg/`、`data/real_labels_nobg/`
に保存。

## 2026-07-28 09:00 JST — Claude (kekcc): specials を新しいラベル源に、LOTO 実行中

最優先の次手（ラベル追加）に着手。人手クリックを増やすのではなく、
E07 specials の既知反応点を使う。

**手法**: 線分の直線が確認済み反応点から 10px 以内を通り、かつ近い方の
端点が反応点から 150px 以内にあるなら、その線分はその事象の本物の飛跡で
ある可能性が高い。判断の根拠は幾何と物理的に確認された反応点であって、
人間が Hough 出力を採点した結果ではない——よって疑似ラベルと違い、
Method A 分類器の意見を CNN に還流させる循環にならない。線分を提案するのは
依然 Hough だが、本物かを決める主体が変わる。

**純度は仮定せず実測する。** 同じ条件を 1 事象あたり 12 個のランダム点でも
評価し、真の反応点が対照中央値の 3 倍以上を選ぶ事象だけ採用:

| 事象 | 候補 | 選択 | 対照中央値 | 比 | |
|---|---|---|---|---|---|
| D005 | 4569 | 42 | 6.0 | 7.0倍 | 採用 |
| D013 | 3340 | 27 | 3.5 | 7.7倍 | 採用 |
| IBUKI | 8074 | 32 | 16.0 | 2.0倍 | **除外** |
| IRRAWADY | 8510 | 45 | 12.5 | 3.6倍 | 採用 |
| MINO | 4850 | 40 | 8.0 | 5.0倍 | 採用 |
| T004 | 4066 | 30 | 6.0 | 5.0倍 | 採用 |
| T011 | 2472 | 30 | 1.5 | 20.0倍 | 採用 |

IBUKI は密度が高く、ランダム点でも真の反応点とほぼ同数を選ぶため、
偶然が大半を占めるので除外。6 事象・正例 214 線分、推定純度は事象により
約 70〜95%。

**効果の本体は正例の量（track 画素 2.7 万 vs 既存 13.9 万）ではなく
タイルの多様性**。学習タイルが 3 → 9 になる。現状 train_loss 0.026 に対し
val_loss 0.98 という過学習への対策として効くことを期待する。

新規ファイル: `src/specials_label_dataset.py`。`train_real.py` に
`--specials` を追加。これらのタイルは**学習専用**で検証分割には入れない
（検証は人手判断のまま）。`pos_weight` は specials も数えるよう修正
（4.16 → 3.73）。

入力（読み取りのみ）: `/gpfs/group/had/sks/Users/shuhei/work/specials_x20/
<event>/image.json`、`e07-fullscan/tests/specials_gt.json`。
出力: `e07-binary-segmentation/data/specials_labels/*.npz`（6 件）と
LSF 配列 55277503（`results/loto/`、`logs/loto/`）。背景修正版の結果は
`results/loto_bg/`・`logs/loto_bg/` に、背景なし版は `results/loto_nobg/`
に保存済み。

## 2026-07-28 19:55 JST — Claude (kekcc): 完了 — specials ラベルは帰無（AUC 0.592 → 0.594）

対照実験（各アーム 4 fold × seed 1、20 epoch、n=512、基準率 43.6%）:

| | precision | recall | 予測陽性率 | AUC |
|---|---|---|---|---|
| specials なし | 48.0% [42.7, 53.4] | 70.4% | 63.9% | 0.592 |
| specials あり | 50.0% [43.7, 56.3] | 54.3% | 47.3% | 0.594 |

層別 AUC は上位100位帯 0.555→0.560、裾帯 0.538→0.543。学習タイルを
3→9 に増やしたが**判別力は動かなかった**。precision/recall の変化は
動作点の移動にすぎず、AUC はまさにそれを補正した指標。

**検出力の注意（先に明記）**: n=512（track 223 / junk 289）での AUC の
標準誤差は Hanley-McNeil で 0.025、差の検出限界は **0.070 AUC**。
よってこの実験は「大きな改善が無い」ことを示すのであって「効果ゼロ」
を示すものではない。

なおベースライン（20 epoch・1 seed、AUC 0.592）は本日朝の 50 epoch・
3 seed の結果（0.597）を再現しており、短縮設定でも妥当。

**解釈**: specials は正例しか供給しない。判別すべきは「線状の junk」と
「線状の本物」の区別で、specials は junk の例を一つも足さずに「これは
本物だ」とだけ教える。しかもモデルは背景修正後でも予測陽性率 64% と
track を過剰予測している。足りなかったのは正例ではなく**junk と track
を分ける情報**。タイル多様性が効かなかったことも同じ解釈と整合する。

**方針への影響**: 幾何による安価なラベル生成は正例側で頭打ち。残る
選択肢は (1) junk 側の教師を増やす＝人手レビュー。ただし**古典と ML が
食い違う箇所**を優先すればクリックあたりの情報量を最大化できる。
(2) 別種の信号——スライス間 3D 整合性、grain density。1 スライスの
見た目だけでは原理的に分離しにくい可能性があり、AUC 0.59 の頭打ちは
その示唆かもしれない。

実行はワークサーバの 4 コア枠で行った（8 ラン、約 4.5 時間）。LSF が
スケジュールしなかったため——本ユーザーの fairshare 優先度が全 queue で
0.000（queue l に 400 件超投入した影響）、加えて queue s は CPU 上限
150 分で 9 タイルでは 12 epoch しか入らない。3 seed 版の LSF ジョブは
投入したまま残してあり、動けば統計が増える。

新規・変更: `src/specials_label_dataset.py`、`train_real.py` の
`--specials`、`scripts/run_local_ab.sh`、`scripts/loto_job.sh`。
結果は `results/local_{sp,nosp}/`。git は引き続き未コミット。

## 2026-07-29 12:45 JST — Claude (kekcc): `/label_disagree` を追加、ラベル破壊バグを発見・修正

「足りないのは junk と track を分ける情報」という結論を受け、古典分類器と
CNN の不一致が大きい順に候補を出すブラウザ用キューを追加した。

**作る前に測定**: 本番 Hough パラメータで 4 タイル計 47,498 候補のうち
**30.2%（14,341 件）が真逆の判定**、確率差 0.5 超が 9.3%、0.7 超が 396 件。
UI を作る価値が十分ある厚みだと確認してから実装した。

**実装**: `/label_disagree`（＋ `/label_disagree_segments`）は
`/label_uncertain` のテンプレートを共用（endpoint とラベルをテンプレート
変数化。コピーはしていない）。CNN 確率はファイル経由
（`e07-binary-segmentation/data/cnn_scores.json`）で渡し、Flask に torch を
持ち込まない。生成は `dump_segments.py --all-candidates --hough 35,30,40` →
新規 `score_candidates.py`。

**応答 84 秒 → 0.12 秒**: ラベルに依存しない計算を毎回やり直していた 2 箇所
——タイルごとの Hough ＋ 約 12,000 セグメントの特徴量抽出と、
`build_training_set()` が全ラベルファイルのタイルで Hough を再実行する処理
——をメモ化（`labeling._cached_features`、
`track_classifier.features_for_record`）。初回のみ約 80 秒のキャッシュ構築。
`/label_uncertain` も同じ恩恵を受けた。

**ラベル破壊バグ（発火前に発見・修正）**: `label_decide` は保存時に
レコードの Hough パラメータを**現在のサーバ既定値で上書き**する。既定値は
2026-07-23 に 35/30/40 へ変更されたが、既存 512 判定はすべて 8/10/20 で
記録され 2026-07-18 以降未更新。決定は候補リストへの添字なので、
**新規に 1 クリック保存すれば 512 判定が全て別の候補集合（24,038 本 vs
12,003 本、順序も独立）を指すよう静かに書き換わる**ところだった。
7/23 以降クリックが無かったため実害はゼロ。対策としてパラメータごとに
ファイルを分けた（一致すれば追記、異なれば `..._z29__t35l30g40.json`）。
実機検証済み: 新規判定は別ファイルに入り、既存ファイルの md5 は不変、
512 判定は無傷。`real_label_dataset.py` は各ファイルのパラメータを読む
設計なので両方とも正しく使える。

**次にラベルする人への注意**: 新規判定は 35/30/40 の候補母集団に貯まり、
既存 512（8/10/20）とは**別母集団**。単純に合計して数えないこと。

変更: 当リポジトリの `module/server/labeling.py`、
`module/track_classifier.py`、`README.md`、`STATUS.md`、
`analysis-note.md`。ML 側は `src/score_candidates.py` 新規、
`src/dump_segments.py` に `--all-candidates` / `--hough` 追加。
fast tests 52 passed。レビュー起動は
`python -m module.server.app --port 8123`。git は未コミット。

## 2026-09-07 — Phase 1-2 着手: `integrate_smallregions` + `pixellist2poly` の移植

**入力（読むだけ）**: `e07/matlab/{integrate_smallregions,pixellist2poly,
isaline3,isaline3a,mindistance_to_polyline,mindistance_tolineseg}.m`、
`e07/matlab/work1.mat`（`x` 41,609点 / `lseg` 1,239線分 / `polylines` 149本）。

**出力（新規・当リポジトリ所有）**: `module/graphdet/polyfit.py`、
`module/graphdet/integrate.py`、`scripts/check_polylines_reference.py`。
`module/graphdet/geom.py` と `__init__.py`、`tests/test_graphdet.py` に追記。

**検証方法**: `work1.mat` の `lseg`（MATLAB 出力）を入力に与えて
`polylines` 149本と照合する。Phase 1-1 と同じく MATLAB 実行は不要。

**移植方針**: Phase 1-1 と同じく、驚くべき MATLAB 挙動（NaN 比較、
first-of-equals な min、round の half-away-from-zero、列優先の find 順）は
そのまま再現しコメントで明示する。定数の再調整は Phase 2 で行う。

**結果（同日）**: 完了。`work1.mat` の `lseg` を入力に polylines を
**149本ちょうど**返し、全長 118,270 px（参照 118,033、差 0.2%）、
全折れ線が参照から 16 px 以内。生 hit からは 24.5 秒/view
（段1 14.0 + 段2 10.5）。fast tests 63 passed、slow 2 passed。

**Phase 1-1 と違い、ビット一致は達成できない**（できないと確認した）。
`resamplingpoly` の hit 選択 `ell>=0` は、折れ線の端の頂点が定義上
その折れ線の一番外の hit の射影であるため厳密に境界に乗る。実測で
**175 chain すべてが始点・終点に `|ell|<1e-8` の hit を1個ずつ持つ**。
MATLAB と NumPy の BLAS の最終 bit の違いで採否が裏返り、端点が約1px
動く。`np.linalg.norm`→`dnrm2` の差し替えでは 97→99 本しか改善せず、
単一の式の違いではないと確認した。方針は「境界 hit は常に含める」
（`_ELL_SLACK_PX = 1e-9`）。逐語版は 150本・最悪 76 px、「常に除く」は
hit ゼロの折れ線が出て例外。採用版は本数が参照と一致し最悪 16 px。

**評価尺度も変えた**: 頂点リスト一致ではなく、1px 再サンプリング後の
曲線 Hausdorff 距離。曲がり角の頂点が hit 数個ずれただけで不一致に
なるのを避けるため。

**MATLAB 側の不具合3件**（analysis-note.md 2026-09-07 に詳述）:
`kousinflag`/`koushinflag` の綴り違い、最終行の要素数不一致で落ちうる
代入、flag=2/3 分岐が全点間距離行列で view 規模に載らないこと。

変更: `module/graphdet/{integrate,polyfit,geom,__init__}.py`、
`scripts/check_polylines_reference.py`、`tests/test_graphdet.py`、
`README.md`、`STATUS.md`、`analysis-note.md`。git は未コミット。

## 2026-09-07 — Phase 1-3: `detectbunki` 移植 + efficiency/purity の初測定

**入力（読むだけ）**: `e07/matlab/detectbunki.m`、`e07/matlab/simdata8.mat`
（`Summary` 10事象分、`dspl` 間引き hit）。
**出力（新規・当リポジトリ所有）**: `module/graphdet/branch.py`、
`scripts/eval_branches.py`。`__init__.py`・`tests/test_graphdet.py`・
`README.md`・`STATUS.md`・`analysis-note.md` を更新。

**結果**: 移植3段が揃った。10事象の真の分岐点 130 個に対し、
一致半径 25 px で **efficiency 96.2% / purity 74.0%**（10 px なら
93.1% / 55.3%）。**efficiency は十分、弱点は purity**（真 130 に対し
215 個を出す）。一致した 125 個のうち 4 個は別の真の分岐点と同じ
再構成頂点に潰れており、分解能はこの数字ほど良くない。

**移植上の判断2件**:
- MATLAB の `linkage`+`cluster`(cutoff 0.5) は 0/1 距離・single linkage
  なので**連結成分そのもの**。密な M×M 距離行列をやめて BFS にした。
- `branch_points()` は**移植ではなく追加**。`detectbunki` はグループしか
  返さないが E07 が要るのは座標なので、グループ化が既に使っている
  共有 hit の重心から導出した。

**MATLAB のバグをもう1件**: 退化した長さ0の線分に対し `v./norm(v)` が
NaN を作り、`min` が NaN を飛ばすことで通常は無害だが、**候補が全部
NaN のとき `min` は NaN と添字1を返し `~isinf(NaN)` が真なので誤接続
する**。移植側は退化線分を inf として明示的に弾いた。事象1（参照照合に
使う事象）には長さ0の線分が無いので、段2の照合結果は不変。

**測定時の注意**: 事象6〜10 の所要が事象1〜5 の約5倍だが、これはデータ
ではなく**ワークサーバの4コア制限**（3段すべてが同じ比率で遅くなって
いる）。素の値は 24.5 秒/view。

fast tests 68 passed。git は未コミット。

## 2026-09-07 — Phase 2: エクスポート格子の較正。30 px は粗すぎると実測

**入力（読むだけ）**: `e07/matlab/{mabiki.m,simdata8.mat}`。
**出力（新規・当リポジトリ所有）**: `module/graphdet/{config,downsample,
simeval}.py`、`scripts/scan_sampling.py`。`module/graphdet/{geom,detectlseg,
integrate,branch,__init__}.py`、`module/matlab_export.py`、
`tests/test_graphdet.py`、`README.md`、`STATUS.md`、`analysis-note.md` を更新。

**結論**: `matlab_export` の `_GRID_CELL_PX = 30` は**分岐点 purity を
78.8% → 17.5% に落とす**。同じシミュレーションを別ブロックで間引き直して
測った（真値は `Summary` 由来なので間引きに影響されない）。膝は **6 px**。
30 px は 2026-07-11 に MATLAB を 2.5時間/tile に収めるため選ばれたもので、
移植で約250倍速くなった今その制約は無い。
→ `_GRAPH_CELL_PX = 6` を新設し export/CLI の既定に。ノイズフィルタと
viewer overlay は 30 px でチューニング済みなので `noise_cell` で分離。

**段の切り分け**: 段1・段2 は 30 px でも無傷（軌跡長 98%、真の頂点 14/14 の
近くに折れ線の頂点がある）。**壊れるのは段3だけ**で、`detectbunki` が
「1.5 px 以内で共有された hit」で判定するため、定数では直らない。
幾何判定（端点近接）の代案も試作したが purity 26% 止まりで**不採用**。

**足場**: `DetectorConfig` に全距離定数を集約。**透過方向の許容値と
長さスケールを分離**したのが要点で、`for_spacing()` は後者だけを直す。
既定は MATLAB 値のままなので参照照合は不変（段1 1,239本 全一致・
最大 2.5e-13 px、段2 149本、段3 eff 92.9%/purity 92.3%）。
`mabiki.m` も移植し `dspl` と完全一致を確認。

**未測定のリスク**: 6 px の実 E07 データでのコスト。シミュレーションは
159本/view だが実 E07 はもっと密。**本番エクスポート前に 1 tile で実測**。
また `z_scale` はまだ MATLAB 値のまま（`E07_Z_SCALE` は定義済み）。

**測定時の注意**: ワークサーバの4コア制限で、掃引の後半は前半の3〜5倍の
時間がかかっている。時間の絶対値は信用しないこと。

fast tests 22 passed（graphdet）、slow 2 passed。git は未コミット。
