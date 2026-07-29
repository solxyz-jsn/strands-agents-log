# Strands Agents OpenTelemetry デモ

Strands Agents で長方形の面積を計算し、モデル呼び出し、ツール実行、エージェントの処理過程を OpenTelemetry のスパンとしてファイルへ出力するデモです。

## 実行方法

必要な Python バージョンは 3.12 以上です。

```bash
uv sync
uv run python main.py
```

質問はコマンドライン引数でも指定できます。

```bash
uv run python main.py "幅12.5メートル、高さ8メートルの長方形の面積は？"
```

実行するには、Strands Agents が使用するモデルへアクセスできる認証設定が別途必要です。

## ログファイル

1 回実行するたびに、実行開始時刻をファイル名にした次のログが作成されます。

```text
logs/YYYYMMDDHHMMSS.log
```

ファイル名の時刻は実行環境のローカル時刻です。一方、JSON 内の `start_time`、`end_time`、`timestamp` は `Z` または `+00:00` で表される UTC 時刻です。

### ログの構成単位

ログ内のトップレベル JSON オブジェクト 1 個が、OpenTelemetry の **1 スパン**、つまり一つの処理区間を表します。ファイル全体はおおむね次の構成です。

```text
{ 1個目のスパン }
{ 2個目のスパン }
...
{ 最後のスパン }

エージェントの最終応答:
（最終応答のプレーンテキスト）
```

このため、ログファイルは次のどちらでもありません。

- 複数のスパンを `[...]` で囲んだ JSON 配列
- 1 行に 1 オブジェクトを収めた JSON Lines（JSONL）

整形済みの JSON オブジェクトが連続し、末尾には JSON ではない最終応答も含まれます。したがって、ファイル全体をそのまま `json.load()` や `jq` へ渡すことはできません。

また、スパンは通常、処理が終了してエクスポートされた順に現れます。親スパンは子スパンより後に終了するため、**ファイル上の並び順と処理の親子順は一致しないことがあります**。処理構造は後述する `span_id` と `parent_id` で判断します。

## スパンの種類

このデモでは、主に次のスパンが出力されます。

| `name` | 表す処理 | 主に確認する内容 |
| --- | --- | --- |
| `invoke_agent Strands Agents` | エージェント呼び出し全体 | 最終応答、全モデル呼び出しの合計トークン数、利用可能なツール |
| `execute_event_loop_cycle` | エージェントの思考・実行ループの 1 サイクル | そのサイクルで扱ったユーザー入力、モデル出力、ツール結果 |
| `chat` | モデルへの 1 回のリクエスト | モデル名、入出力、トークン数、応答時間、終了理由 |
| `execute_tool calculate_rectangle_area` | `calculate_rectangle_area` の 1 回の実行 | ツール引数、戻り値、実行状態 |

標準の質問では、一般に次のような処理になります。

```text
invoke_agent Strands Agents
├── execute_event_loop_cycle        # 1回目のサイクル
│   ├── chat                         # モデルがツール使用を選択
│   └── execute_tool ...             # 面積計算ツールを実行
└── execute_event_loop_cycle        # 2回目のサイクル
    └── chat                         # ツール結果から最終応答を生成
```

実ログでは子スパンから先に出力されるため、上の順ではなく、たとえば `chat`、`execute_tool`、`execute_event_loop_cycle`、最後に `invoke_agent` という順で現れます。ツールを使わない場合や複数回使う場合は、スパンの種類と個数も変わります。

## トップレベルキーの意味

スパンは次のような形をしています。

```json
{
    "name": "chat",
    "context": {
        "trace_id": "0x...",
        "span_id": "0x...",
        "trace_state": "[]"
    },
    "kind": "SpanKind.INTERNAL",
    "parent_id": "0x...",
    "start_time": "2026-07-29T05:20:57.753026Z",
    "end_time": "2026-07-29T05:21:00.175855Z",
    "status": {
        "status_code": "OK"
    },
    "attributes": {},
    "events": [],
    "links": [],
    "resource": {}
}
```

| キー | 意味 |
| --- | --- |
| `name` | スパン名。`chat` や `execute_tool ...` など、処理の種類を示す |
| `context.trace_id` | 一連の処理全体を識別する ID。同じエージェント呼び出しに属するスパンは同じ値を持つ |
| `context.span_id` | そのスパン自身を識別する ID |
| `context.trace_state` | 分散トレースでベンダー固有情報などを伝播する領域。このデモでは空 |
| `kind` | スパンの役割。このデモの `SpanKind.INTERNAL` は、プロセス内部の処理であることを示す |
| `parent_id` | 親スパンの `span_id`。ルートの `invoke_agent ...` は親を持たないため `null` |
| `start_time` / `end_time` | スパンの開始・終了時刻。両者の差が、そのスパン全体の所要時間 |
| `status.status_code` | スパンの結果。`OK` は正常終了、`ERROR` はエラー、`UNSET` は状態が明示されていないことを示す |
| `attributes` | モデル名、トークン数、ツール名など、そのスパンに付随する検索・集計向け情報 |
| `events` | スパン内の特定時点で発生した入出力などのイベント |
| `links` | 親子関係とは別に関連するスパンへのリンク。このデモでは通常空 |
| `resource` | スパンを生成したサービスや OpenTelemetry SDK の情報 |

### `trace_id`、`span_id`、`parent_id` の読み方

処理の親子関係は次の手順で追えます。

1. `parent_id: null` のスパンを探す。このデモでは `invoke_agent Strands Agents` がルートになる。
2. ルートの `context.span_id` と同じ値を `parent_id` に持つスパンを探す。
3. 見つかった各スパンについて同じ操作を繰り返す。
4. 複数の実行ログをまとめて扱う場合は、最初に `context.trace_id` が同じスパンだけへ絞る。

たとえば、ある `chat` の `parent_id` が `execute_event_loop_cycle` の `span_id` と同じなら、そのモデル呼び出しはそのサイクル内で実行されたと分かります。

## `attributes` の主なキー

### 共通・エージェント関連

| キー | 意味 |
| --- | --- |
| `gen_ai.operation.name` | 処理種別。`invoke_agent`、`execute_event_loop_cycle`、`chat`、`execute_tool` など |
| `gen_ai.system` | テレメトリを生成した生成 AI システム。このデモでは `strands-agents` |
| `gen_ai.event.start_time` / `gen_ai.event.end_time` | 生成 AI 処理として記録された開始・終了時刻 |
| `gen_ai.agent.name` | エージェント名 |
| `gen_ai.agent.tools` | エージェントが利用できるツール名の一覧 |
| `system_prompt` | エージェントへ設定したシステムプロンプト |
| `event_loop.cycle_id` | イベントループのサイクルを識別する ID |
| `event_loop.parent_cycle_id` | 前のサイクルなど、親サイクルの ID |

### モデル呼び出し関連

| キー | 意味 |
| --- | --- |
| `gen_ai.request.model` | 呼び出したモデルの ID |
| `gen_ai.usage.prompt_tokens` / `gen_ai.usage.input_tokens` | モデルへ入力したトークン数。現在の実装では同じ値が両方の名前で記録される |
| `gen_ai.usage.completion_tokens` / `gen_ai.usage.output_tokens` | モデルが出力したトークン数。現在の実装では同じ値が両方の名前で記録される |
| `gen_ai.usage.total_tokens` | 入力と出力を合わせた合計トークン数 |
| `gen_ai.usage.cache_read_input_tokens` | プロンプトキャッシュから読み出した入力トークン数 |
| `gen_ai.usage.cache_write_input_tokens` | プロンプトキャッシュへ書き込んだ入力トークン数 |
| `gen_ai.server.time_to_first_token` | 最初のトークンを受け取るまでの時間（ミリ秒） |
| `gen_ai.server.request.duration` | モデルリクエストのレイテンシー（ミリ秒） |

`chat` のトークン数は 1 回のモデル呼び出しに対する値です。`invoke_agent ...` のトークン数は、エージェント実行中に行われたモデル呼び出しの合計です。

`start_time` と `end_time` の差はクライアント側の処理も含むスパン全体の時間です。一方、`gen_ai.server.*` はモデルリクエストについて取得されたミリ秒単位のメトリクスなので、両者は必ずしも一致しません。

### ツール実行関連

| キー | 意味 |
| --- | --- |
| `gen_ai.tool.name` | 実行したツール名 |
| `gen_ai.tool.call.id` | モデルによるツール呼び出しを識別する ID。要求と結果を対応付けるために使う |
| `gen_ai.tool.description` | ツールの説明 |
| `gen_ai.tool.json_schema` | モデルへ提示したツール引数の JSON Schema |
| `gen_ai.tool.status` | ツールの実行結果。このデモの正常時は `success` |

## `events` の読み方

`events` は、スパンの途中で発生したメッセージや結果を時系列で保持します。各イベントには次のキーがあります。

| キー | 意味 |
| --- | --- |
| `name` | イベントの種類 |
| `timestamp` | イベントが発生した UTC 時刻 |
| `attributes` | メッセージ本文、終了理由、ツール呼び出し ID など、イベント固有の情報 |

主なイベント名は次のとおりです。

| イベント名 | 意味 |
| --- | --- |
| `gen_ai.system.message` | モデルへ渡したシステムメッセージ |
| `gen_ai.user.message` | ユーザーの入力 |
| `gen_ai.assistant.message` | 会話履歴に含まれるアシスタントのメッセージ |
| `gen_ai.tool.message` | ツールの入力または実行結果 |
| `gen_ai.choice` | モデルが生成した結果。通常の応答だけでなく、ツール使用要求を含む場合もある |

イベント内でよく見る属性は次のとおりです。

| 属性 | 意味 |
| --- | --- |
| `content` | システム、ユーザー、アシスタント、ツールのメッセージ内容 |
| `message` | モデルが選択・生成したメッセージ |
| `finish_reason` | 生成を終えた理由。`tool_use` はツール呼び出しへ進み、`end_turn` はそのターンが完了したことを示す |
| `tool.result` | ツールの実行結果 |
| `id` | 関連するツール呼び出し ID |

`content`、`message`、`tool.result`、`gen_ai.tool.json_schema` などの値には、JSON に見える内容が **文字列として**格納される場合があります。その場合、外側のスパン JSON を解析した後、必要に応じてその文字列をもう一度 JSON として解析します。

## `resource` の主なキー

| キー | 意味 |
| --- | --- |
| `telemetry.sdk.language` | 計装に使用した言語。このデモでは `python` |
| `telemetry.sdk.name` | 使用したテレメトリ SDK。このデモでは `opentelemetry` |
| `telemetry.sdk.version` | OpenTelemetry SDK のバージョン |
| `service.name` | スパンを生成したサービス名 |
| `service.version` | サービスまたはライブラリのバージョン |
| `service.instance.id` | 実行中のサービスインスタンスを識別する ID |
| `schema_url` | Resource 属性が準拠するスキーマの URL。このデモでは未設定 |

## ログを読むときの手順

問題調査では、次の順で見ると処理を追いやすくなります。

1. **全体結果を確認する**：`parent_id: null` の `invoke_agent ...` を探し、`status`、実行時間、合計トークン数、`gen_ai.choice` の最終応答を見る。
2. **処理構造を復元する**：`span_id` と `parent_id` を対応付け、どのサイクルでどのモデル・ツール呼び出しが行われたか確認する。
3. **モデル呼び出しを確認する**：各 `chat` でモデル ID、トークン数、応答時間、`finish_reason`、メッセージ内容を見る。
4. **ツール実行を確認する**：`execute_tool ...` でツール名、`gen_ai.tool.call.id`、入力、出力、`gen_ai.tool.status` を見る。
5. **時系列を確認する**：必要に応じて `start_time`、`end_time`、イベントの `timestamp` で並べる。ファイル上の順番だけには依存しない。

トップレベルのスパン名だけを一覧表示するには、次のコマンドが使えます。

```bash
grep -n '^    "name":' logs/YYYYMMDDHHMMSS.log
```

最新のログを読む場合は、たとえば次のようにします。

```bash
latest_log=$(ls -t logs/*.log | head -n 1)
less "$latest_log"
```

## 取り扱い上の注意

ログにはシステムプロンプト、ユーザー入力、モデル出力、ツールの引数と結果が記録されます。認証情報、個人情報、機密情報を入力した場合、それらも保存される可能性があります。ログを共有したりリポジトリへコミットしたりする前に、内容を確認して必要なマスキングを行ってください。
