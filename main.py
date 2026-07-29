"""Strands AgentsとOpenTelemetryのファイルトレースを試すデモ。

カスタムツールで長方形の面積を計算し、モデル呼び出し、ツール呼び出し、
最終応答を ``logs/YYYYMMDDHHMMSS.log`` へ出力する。

実行例:
    uv run python main.py "幅12.5メートル、高さ8メートルの長方形の面積は？"
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import TextIO

from opentelemetry.sdk.trace import ReadableSpan
from strands import Agent, tool
from strands.telemetry import StrandsTelemetry

DEFAULT_PROMPT = "幅12.5メートル、高さ8メートルの長方形の面積を計算してください。"
LOG_DIRECTORY = Path(__file__).resolve().parent / "logs"
SYSTEM_PROMPT = (
    "あなたは簡潔で親切な日本語アシスタントです。"
    "面積の計算では、必ずcalculate_rectangle_areaツールを使用してください。"
)


@tool
def calculate_rectangle_area(width: float, height: float) -> float:
    """長方形の面積を計算する。

    Args:
        width: 長方形の幅。0以上の数値を指定する。
        height: 長方形の高さ。0以上の数値を指定する。

    Returns:
        幅と高さを掛けて求めた長方形の面積。

    Raises:
        ValueError: 幅または高さに負の値が指定された場合。
    """
    if width < 0 or height < 0:
        raise ValueError("幅と高さには0以上の値を指定してください。")

    return width * height


def create_log_path() -> Path:
    """実行時刻を名前にしたログファイルのパスを作成する。

    Returns:
        スクリプト直下の ``logs/YYYYMMDDHHMMSS.log``。
    """
    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    return LOG_DIRECTORY / datetime.now().strftime("%Y%m%d%H%M%S.log")


def format_span_as_utf8(span: ReadableSpan) -> str:
    """OpenTelemetryスパンを日本語をエスケープしないJSONへ変換する。"""
    span_data = json.loads(span.to_json())
    return json.dumps(span_data, ensure_ascii=False, indent=4) + "\n"


def setup_file_tracing(log_file: TextIO) -> StrandsTelemetry:
    """OpenTelemetryスパンを指定したログファイルへ送るように設定する。

    Args:
        log_file: JSON形式のOpenTelemetryスパンを書き込むファイル。

    Returns:
        ファイル出力先を設定済みのテレメトリオブジェクト。
    """
    telemetry = StrandsTelemetry()
    telemetry.setup_console_exporter(out=log_file, formatter=format_span_as_utf8)
    return telemetry


def create_agent() -> Agent:
    """面積計算ツールを利用できるデモ用エージェントを作成する。

    Returns:
        ``calculate_rectangle_area`` を登録したStrandsエージェント。
    """
    return Agent(
        system_prompt=SYSTEM_PROMPT,
        tools=[calculate_rectangle_area],
        callback_handler=None,
    )


def parse_args() -> argparse.Namespace:
    """コマンドライン引数からエージェントへ渡すプロンプトを取得する。

    Returns:
        解析済みのコマンドライン引数。プロンプトは ``prompt`` に格納される。
    """
    parser = argparse.ArgumentParser(
        description="OpenTelemetryトレースを日時付きログへ出力してStrandsエージェントを実行します。"
    )
    parser.add_argument(
        "prompt",
        nargs="*",
        help="エージェントへ渡すプロンプト。省略時は面積計算の例を使用します。",
    )
    return parser.parse_args()


def main() -> None:
    """日時付きログへのトレース出力を有効化してエージェントを実行する。"""
    args = parse_args()
    prompt = " ".join(args.prompt) if args.prompt else DEFAULT_PROMPT
    log_path = create_log_path()

    with log_path.open("w", encoding="utf-8") as log_file:
        # Agentを作る前に設定し、ファイルを閉じる前に全スパンを書き出す。
        telemetry = setup_file_tracing(log_file)
        try:
            agent = create_agent()
            result = agent(prompt)
            print(f"\nエージェントの最終応答:\n{result}", file=log_file)
        finally:
            telemetry.tracer_provider.force_flush()


if __name__ == "__main__":
    main()
