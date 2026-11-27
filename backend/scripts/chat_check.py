"""The Phase 3 real-provider check of chat, through a running server. Made-up text only.

Start a temporary server with Gemini for that process only, then run this against it:

    backend> set MODEL_PROVIDER=gemini & .venv\\Scripts\\python -m uvicorn app.main:app --port 8020
    backend> .venv\\Scripts\\python -m scripts.chat_check --base http://127.0.0.1:8020 --send

At most 4 model calls: two turns, one answer that is stopped, and its retry. Repeating the first
turn must make no call. Registers one throwaway account and deletes it at the end. Without
``--send`` it only lists the steps. Exit code 0 means every check passed.
"""

import argparse
import json
import sys
import threading
import time
import uuid

import httpx
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import get_session_factory
from app.modules.providers.tables import ProviderSpend
from scripts.delete_check_accounts import delete_accounts

ORIGIN = "http://localhost:3000"  # one of ALLOWED_ORIGINS in development
INSTRUCTIONS = (
    "You answer questions for Petal & Pine, a made-up flower shop. Answer in two short "
    "sentences, in plain text."
)
TURNS = [
    "Hello! I am planning a small birthday bouquet. Which flowers would you suggest?",
    "What was the occasion I mentioned? Answer in a few words.",
    "Write a long paragraph about the history of the shop's made-up founder.",
]
STEPS = [
    "turn 1 (1 call)",
    "turn 2, which needs turn 1 as history (1 call)",
    "turn 3, stopped after its first piece (1 call, may be charged)",
    "retry of turn 3 with the same request (1 call)",
    "repeat of turn 1 with the same request (no call)",
]

results: list[tuple[str, bool]] = []


def check(name: str, ok: bool) -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}", flush=True)
    results.append((name, ok))


def spend() -> tuple[int, int]:
    """Calls recorded by the spending limit, and their cost in nano-dollars."""
    with get_session_factory()() as session:
        row = session.execute(
            select(func.count(), func.coalesce(func.sum(ProviderSpend.cost_nano_usd), 0))
        ).one()
        return int(row[0]), int(row[1])


def events(response: httpx.Response):
    buffer = ""
    for text in response.iter_text():
        buffer += text
        while "\n\n" in buffer:
            block, buffer = buffer.split("\n\n", 1)
            name, data = "", ""
            for line in block.split("\n"):
                if line.startswith("event: "):
                    name = line[7:]
                elif line.startswith("data: "):
                    data += line[6:]
            yield name, json.loads(data)


def stream(client: httpx.Client, chat: str, request_id: str, content: str, on_piece=None):
    """``chat`` ends with the notice that was shown, as ``?disclosure=...``."""
    body = {"request_id": request_id, "content": content}
    seen: list[tuple[str, dict]] = []
    path, query = chat.split("?")
    url = f"{path}/messages/stream?{query}"
    with client.stream("POST", url, json=body, timeout=60) as response:
        if response.status_code != 200:
            response.read()
            return response.status_code, [("refused", response.json()["error"])]
        for name, data in events(response):
            seen.append((name, data))
            if name == "piece" and on_piece is not None:
                on_piece()
                on_piece = None
    return 200, seen


def run(base: str) -> None:
    email = f"browser-check-chat-real-{int(time.time())}@example.com"
    client = httpx.Client(base_url=base, headers={"Origin": ORIGIN}, timeout=30)
    try:
        password = f"check {uuid.uuid4()}"
        registered = client.post("/api/auth/register", json={"email": email, "password": password})
        check("a throwaway account is registered", registered.status_code == 201)
        workspace = client.get("/api/workspaces").json()[0]["id"]
        builder = client.get(f"/api/workspaces/{workspace}/agent-builder").json()
        check("the server uses Gemini", builder.get("disclosure", "none") != "none")
        disclosure = builder["disclosure"]
        agents = f"/api/workspaces/{workspace}/agents"
        agent = client.post(agents, json={"name": "Petal", "instructions": INSTRUCTIONS}).json()
        chats = f"{agents}/{agent['id']}/conversations"
        chat = f"{chats}/{client.post(chats).json()['id']}"
        shown = f"{chat}?disclosure={disclosure}"
        before = spend()

        first = str(uuid.uuid4())
        status, seen = stream(client, shown, first, TURNS[0])
        names = [name for name, _ in seen]
        ok = status == 200 and names[0] == "message" and names[-1] == "done"
        if not ok:
            print("      ", status, seen[-1:])
        check("turn 1 is answered in pieces and stored", ok and "piece" in names)

        status, seen = stream(client, shown, str(uuid.uuid4()), TURNS[1])
        answer = seen[-1][1]["answer"]["content"] if seen and seen[-1][0] == "done" else ""
        check("turn 2 is answered", status == 200 and answer != "")
        check("and remembers turn 1", "birthday" in answer.lower())
        print(f"      turn 2 answer: {answer!r}")

        third = str(uuid.uuid4())
        stopped: list[int] = []

        def stop_now() -> None:
            def post() -> None:
                stopped.append(
                    client.post(f"{chat}/messages/stop", json={"request_id": third}).status_code
                )

            thread = threading.Thread(target=post)
            thread.start()
            threads.append(thread)

        threads: list[threading.Thread] = []
        status, seen = stream(client, shown, third, TURNS[2], on_piece=stop_now)
        for thread in threads:
            thread.join(30)
        last = seen[-1] if seen else ("", {})
        check("turn 3 is stopped", stopped == [204] and last[0] in ("error", "done"))
        if last[0] == "error":
            check("and reported as stopped", last[1]["code"] == "answer_stopped")
        else:
            print("      the answer was complete before the stop arrived")
        kept = client.get(f"{chat}/messages").json()["items"]
        unanswered = kept[-1]["role"] == "user" and kept[-1]["request_id"] == third
        check("the stopped answer is not stored", last[0] == "done" or unanswered)

        status, seen = stream(client, shown, third, TURNS[2])
        check("retrying turn 3 answers it", status == 200 and seen[-1][0] == "done")
        kept = client.get(f"{chat}/messages").json()["items"]
        contents = [message["content"] for message in kept]
        check("without storing the message twice", contents.count(TURNS[2]) == 1)

        calls_before_repeat = spend()[0]
        status, seen = stream(client, shown, first, TURNS[0])
        check("repeating turn 1 returns the stored answer", seen[-1][0] == "done")
        check("without a call", spend()[0] == calls_before_repeat)

        calls, cost = (now - then for now, then in zip(spend(), before, strict=True))
        check("at most 4 calls", calls <= 4)
        print(f"      calls: {calls}, cost: ${cost / 1e9:.6f} at the configured prices")
    finally:
        client.close()
        with get_session_factory()() as session:
            deleted = delete_accounts(session, [email])
        check("the throwaway account is deleted", deleted == 1)


def main() -> int:
    parser = argparse.ArgumentParser(description="The Phase 3 real-provider check of chat.")
    parser.add_argument("--base", default="http://127.0.0.1:8020")
    parser.add_argument("--send", action="store_true", help="really run it against the server")
    arguments = parser.parse_args()
    if not arguments.send:
        print("Steps:", *STEPS, sep="\n  ")
        print("Nothing was sent. Add --send to run it against", arguments.base)
        return 0
    get_settings()
    run(arguments.base)
    return 0 if results and all(ok for _, ok in results) else 1


if __name__ == "__main__":
    sys.exit(main())
