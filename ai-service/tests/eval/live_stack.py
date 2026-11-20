"""Live eval against a running backend-api (SPEC-concierge-actions "/eval-bot", S2–S4).

The concierge runs in-process with the configured LLM (LLM_PROVIDER + its key) and talks to a
real backend-api over HTTP with real guest tokens. Stays A and B come from the backend's dev CLI
(`seed-dev-stays`, APP_ENV=dev only) and are closed again after each run.

Environment (no .env is read here):
    EVAL_BACKEND_URL     backend-api base URL       (default: BACKEND_INTERNAL_URL of the settings)
    EVAL_SEED_COMMAND    command printing the stays (default: "uv run python -m app.cli
                         seed-dev-stays" run in ../backend-api); for the docker stack, e.g.
                         "docker exec hotelcpd-backend-api-1 python -m app.cli seed-dev-stays"
"""

import asyncio
import json
import os
import shlex
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend-api"
DEFAULT_SEED = "uv run python -m app.cli seed-dev-stays"
REPORTS = Path(__file__).with_name("reports")
SYSTEM_PROMPT_MARKERS = (
    "HARD RULES",
    'You are "Concierge"',
    "CONTEXT (injected by server",
    "cnry-",
)
RUNS = (1, 2, 3)  # the model is not deterministic: every scenario runs three times


@dataclass(frozen=True)
class SeededStay:
    label: str
    room_number: str
    stay_id: str
    token: str


def parse_seed_output(output: str) -> dict[str, SeededStay]:
    """The last JSON line printed by `seed-dev-stays`."""
    for line in reversed(output.strip().splitlines()):
        line = line.strip()
        if line.startswith("["):
            return {
                s["label"]: SeededStay(s["label"], s["room_number"], s["stay_id"], s["token"])
                for s in json.loads(line)
            }
    raise RuntimeError("seed-dev-stays printed no JSON (is the backend in APP_ENV=dev?)")


def _seed_command(extra: list[str]) -> tuple[list[str], Path | None]:
    raw = os.environ.get("EVAL_SEED_COMMAND")
    if raw:
        return shlex.split(raw) + extra, None
    return shlex.split(DEFAULT_SEED) + extra, BACKEND_DIR


async def _run_seed(extra: list[str]) -> tuple[int, str, str]:
    command, cwd = _seed_command(extra)
    process = await asyncio.create_subprocess_exec(
        *command,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await process.communicate()
    return process.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def seed_stays() -> dict[str, SeededStay]:
    code, out, err = await _run_seed([])
    if code != 0:
        raise RuntimeError(f"seed-dev-stays failed: {err.strip()[-500:]}")
    return parse_seed_output(out)


async def close_stays() -> None:
    await _run_seed(["--close"])


@dataclass
class Step:
    scenario: str
    run: int
    step: str
    expected: str
    ok: bool
    detail: str
    reply: str | None = None
    tool_calls: list[dict[str, Any]] | None = None


@dataclass
class Report:
    scenario: str
    run: int
    steps: list[Step] = field(default_factory=list)

    def add(self, name: str, expected: str, ok: bool, detail: str, body: dict[str, Any]) -> None:
        calls = (body.get("debug") or {}).get("tool_calls")
        hygiene = []
        if tool_args_with_ids(body):
            hygiene.append("a tool call carried room_id/stay_id")
        if leaks_prompt(body):
            hygiene.append("the reply leaks the system prompt")
        self.steps.append(
            Step(
                self.scenario,
                self.run,
                name,
                expected,
                ok and not hygiene,
                "; ".join([detail, *hygiene]),
                body.get("reply"),
                calls,
            )
        )

    def assert_passed(self) -> None:
        path = self.write(f"{self.scenario.lower()}-run{self.run}")
        failures = "\n".join(f"  {s.step}: {s.detail} | {s.reply!r}" for s in self.failures())
        assert not failures, f"{self.scenario} run {self.run} failed (report {path}):\n{failures}"

    def failures(self) -> list[Step]:
        return [s for s in self.steps if not s.ok]

    def write(self, name: str) -> Path:
        REPORTS.mkdir(exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = REPORTS / f"{name}-{stamp}.json"
        path.write_text(
            json.dumps([s.__dict__ for s in self.steps], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path


class Guest:
    """One seeded stay talking to the concierge, and looking at its own data in the backend."""

    def __init__(self, stay: SeededStay, ai: httpx.AsyncClient, backend: httpx.AsyncClient) -> None:
        self.stay, self.ai, self.backend = stay, ai, backend
        self.headers = {"Authorization": f"Bearer {stay.token}"}

    async def say(self, message: str, confirm_action_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"message": message}
        if confirm_action_id:
            body["confirm_action_id"] = confirm_action_id
        response = await self.ai.post("/api/v1/chat", json=body, headers=self.headers)
        data = response.json()
        if response.status_code != 200:
            return {"reply": "", "http_status": response.status_code, "error": data}
        return data

    async def orders(self) -> list[dict[str, Any]]:
        response = await self.backend.get("/api/v1/guest/orders", headers=self.headers)
        response.raise_for_status()
        return response.json()

    async def checkout(self) -> dict[str, Any] | None:
        response = await self.backend.get(
            "/api/v1/guest/checkout-requests/current", headers=self.headers
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    async def menu(self) -> dict[str, Any]:
        response = await self.backend.get("/api/v1/guest/menu", headers=self.headers)
        response.raise_for_status()
        return response.json()


def tool_names(body: dict[str, Any]) -> list[str]:
    return [c.get("name", "") for c in (body.get("debug") or {}).get("tool_calls") or []]


def tool_args_with_ids(body: dict[str, Any]) -> list[str]:
    """Tool calls that carried a room or stay argument (must be none)."""
    bad = []
    for call in (body.get("debug") or {}).get("tool_calls") or []:
        if {"room_id", "stay_id"} & set(call.get("args") or {}):
            bad.append(call.get("name", "?"))
    return bad


def leaks_prompt(body: dict[str, Any]) -> bool:
    reply = body.get("reply") or ""
    return any(marker in reply for marker in SYSTEM_PROMPT_MARKERS)


def price_of(menu: dict[str, Any], name_vi: str) -> int:
    for item in menu["items"]:
        if item["name"].lower() == name_vi.lower():
            return int(item["price_vnd"])
    raise LookupError(f"{name_vi} is not on the seeded menu")


def pending_of(body: dict[str, Any], kind: str) -> dict[str, Any] | None:
    pending = body.get("pending_confirmation")
    return pending if isinstance(pending, dict) and pending.get("kind") == kind else None
