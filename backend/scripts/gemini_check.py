"""The real-provider test: one made-up draft and one short stream, under the spending limit.

Run from backend/. Without ``--send`` it only shows what would be sent, and calls nothing.

    .venv\\Scripts\\python -m scripts.gemini_check
    .venv\\Scripts\\python -m scripts.gemini_check --send

It uses Gemini whatever MODEL_PROVIDER says, with the key, model and limits from backend/.env. The
key is never shown. Exit code 0 means that both calls worked.
"""

import argparse
import json
import os
import sys
import time

os.environ["MODEL_PROVIDER"] = "gemini"

from app.core.config import get_settings
from app.core.logs import configure_logging
from app.modules.agent_builder.prompt import build_messages
from app.modules.agent_builder.schemas import Answers
from app.modules.agent_builder.service import MAX_OUTPUT_TOKENS, parse_draft
from app.modules.providers.contract import Completion, Message, ProviderError, Role
from app.modules.providers.gemini import GeminiProvider
from app.modules.providers.models import GEMINI_MODELS
from app.modules.providers.selection import get_provider
from app.modules.providers.spending import NANO, worst_case

DRAFT = build_messages(
    Answers(
        purpose="Help customers of a made-up flower shop",
        tasks="Answer questions about opening hours and bouquets",
        tone="Friendly and short",
        constraints="Never promise a discount",
    ).model_dump()
)
STREAM = [
    Message(Role.SYSTEM, "Answer in plain text."),
    Message(
        Role.USER,
        "Write four sentences about a made-up flower shop called Petal & Pine and its owner's "
        "clumsy cat.",
    ),
]
Calls = list[tuple[str, list[Message], int]]
CALLS: Calls = [("draft", DRAFT, MAX_OUTPUT_TOKENS), ("stream", STREAM, 300)]


def show(calls: Calls) -> None:
    settings = get_settings()
    spec = GEMINI_MODELS[settings.gemini_model]
    shown = GeminiProvider("not the real key", spec)
    for name, messages, tokens in calls:
        url, body = shown.request(messages, tokens)
        print(f"--- {name}: POST {url}")
        print("header: x-goog-api-key: (the key, not shown)")
        print(json.dumps(body, indent=2, ensure_ascii=False))
        print(f"at most ${worst_case(spec, messages, tokens) / NANO:.4f} at paid prices\n")


def send(calls: Calls) -> bool:
    provider = get_provider()
    assert provider is not None
    timeout = get_settings().provider_timeout_seconds
    good = True
    for name, messages, tokens in calls:
        started, pieces = time.monotonic(), 0
        try:
            if name == "draft":
                result = provider.complete(
                    messages, timeout_seconds=timeout, max_output_tokens=tokens
                )
                if result.text.lstrip().startswith("```"):  # made-up answers, so not private
                    print("fenced, starts with:", ascii(result.text[:200]))
                print(parse_draft(result.text).model_dump_json(indent=2))
            else:
                result = None
                for item in provider.stream(
                    messages, timeout_seconds=timeout, max_output_tokens=tokens
                ):
                    if isinstance(item, Completion):
                        result = item
                    else:
                        pieces += 1
                assert result is not None
                print(result.text, f"({pieces} pieces)")
            print(
                f"PASS  {name}: {result.input_tokens} tokens in, {result.output_tokens} out, "
                f"{time.monotonic() - started:.1f} s"
            )
        except ProviderError as error:
            print(f"FAIL  {name}: {error.code}, {time.monotonic() - started:.1f} s")
            good = False
            break
        except Exception as error:  # noqa: BLE001 - only the kind: it may hold text
            print(f"FAIL  {name}: {getattr(error, 'code', type(error).__name__)}")
            good = False
    return good


def main() -> int:
    parser = argparse.ArgumentParser(description="The real-provider test.")
    parser.add_argument("--send", action="store_true", help="really call Google")
    parser.add_argument("--only", choices=["draft", "stream"], help="one call instead of both")
    arguments = parser.parse_args()
    configure_logging("INFO")
    get_settings().check_gemini()
    calls = [call for call in CALLS if arguments.only in (None, call[0])]
    if arguments.send:
        return 0 if send(calls) else 1
    show(calls)
    print("Nothing was sent. Add --send to call Google.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
