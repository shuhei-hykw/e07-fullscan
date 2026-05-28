# Notion Research Log Setup — Claude Code向け説明

## 概要

物理学実験の研究ログ・commitログをNotionで管理するための構造を構築した。
Claude CodeからNotion APIを通じて日付ごとのログエントリを自動生成することを想定している。

---

## Notionワークスペース構造

```
🔬 Research
└── ⚡ J-PARC E07
    ├── fullscan software      [Database]
	    ├── image-pre-processing   [Database]
		    ├── graph-network          [Database]
			    └── event-analysis         [Database]
				```

				- **Research** がトップページ
				- **J-PARC E07** が実験単位のページ（今後 E16 など別実験も同階層に追加予定）
				- 各タスクがデータベース（DB）として存在し、日付ごとのエントリを持つ

				---

				## 各データベースのスキーマ

				全タスクDBは共通スキーマ：

				| プロパティ | 型 | 値 |
				|---|---|---|
				| Title | TITLE | 日付や作業タイトル（例: 2026-05-27） |
				| Date | DATE | 作業日 |
				| Status | SELECT | `Todo` / `In Progress` / `Done` |
				| Type | SELECT | `Experiment` / `Commit` / `Analysis` / `Meeting` |
				| Summary | RICH_TEXT | その日の一行メモ |

				各エントリのページ本文に詳細ログを記述する（実験条件・手順・結果 または commitの変更内容・理由・次ステップ）。

				---

				## Notion ページID一覧

				| ページ/DB | Notion URL |
				|---|---|
				| 🔬 Research | https://www.notion.so/36d4f459502281ee86aef72dc9a5432e |
				| ⚡ J-PARC E07 | https://www.notion.so/36d4f4595022811c8fa1d1eeadc2283f |
				| fullscan software DB | https://www.notion.so/77fe90fddd4e4f7cb3c69eb4f6f97887 |
				| image-pre-processing DB | https://www.notion.so/7849f15c90f643eb97a471342e02e42d |
				| graph-network DB | https://www.notion.so/eb20070bee5c4f598a081318492de4fc |
				| event-analysis DB | https://www.notion.so/a14484f2b9014925bf0dad5079932e25 |

				---

				## Claude Codeからの操作イメージ

				### 想定ユースケース
				- 作業開始時に当日のエントリをDBに自動作成
				- git commitのタイミングでcommitログをNotionに書き込む
				- 解析スクリプト実行後に結果サマリーをページ本文に追記

				### Pythonでのエントリ作成例（notion-clientライブラリ使用）

				```python
				from notion_client import Client

				notion = Client(auth="NOTION_API_TOKEN")

				# fullscan software DBにエントリを追加
				notion.pages.create(
				    parent={"database_id": "77fe90fddd4e4f7cb3c69eb4f6f97887"},
					    properties={
						        "Title": {"title": [{"text": {"content": "2026-05-27"}}]},
								        "Date": {"date": {"start": "2026-05-27"}},
										        "Status": {"select": {"name": "In Progress"}},
												        "Type": {"select": {"name": "Commit"}},
														        "Summary": {"rich_text": [{"text": {"content": "ここに一行メモ"}}]},
																    },
																	    children=[
																		        {
																				            "object": "block",
																							            "type": "heading_2",
																										            "heading_2": {"rich_text": [{"text": {"content": "What I did"}}]}
																													        },
																															        {
																																	            "object": "block",
																																				            "type": "paragraph",
																																							            "paragraph": {"rich_text": [{"text": {"content": "変更内容をここに記述"}}]}
																																										        },
																																												    ]
																																													)
																																													```

																																													### MCPサーバー経由での連携（推奨）

																																													Claude CodeにNotion MCPサーバーを設定すると、自然言語でNotionを操作できる。

																																													```json
																																													// claude_code_config.json（MCP設定）
																																													{
																																													  "mcpServers": {
																																													      "notion": {
																																														        "command": "npx",
																																																      "args": ["-y", "@notionhq/notion-mcp-server"],
																																																	        "env": {
																																																			        "NOTION_API_TOKEN": "YOUR_TOKEN_HERE"
																																																					      }
																																																						      }
																																																							    }
																																																								}
																																																								```

																																																								---

																																																								## 今後の拡張方針

																																																								- 別実験（例: J-PARC E16）を追加する場合は **J-PARC E07** と同階層に新ページ＋同構造のDBを作成
																																																								- タスクを追加する場合は J-PARC E07 の下に同スキーマのDBを追加
																																																								- 将来的にタスク横断での日付検索・集計が必要になれば、全DBをまとめた親DBの設計も検討
