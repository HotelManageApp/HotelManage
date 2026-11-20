"""Live eval of the concierge guide (SPEC-concierge-guide "Eval live", T43; /eval-bot S1).

Runs every question in guide_cases.yaml through the real POST /api/v1/chat with the configured
LLM (LLM_PROVIDER + its API key from the environment) and a backend stand-in serving the eval KB.
Pass bar: ≥ 95% correct, 0 invented facts, p95 latency < 8 s.

Opt-in, never in CI (it calls a paid model):
    uv run pytest -q -m live tests/eval/test_guide.py
A JSON report is written to tests/eval/reports/ (git-ignored).
"""

import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.core.backend_client import BackendClient
from app.core.config import ConfigError, load_settings
from app.main import create_app
from tests.eval.support import TOKEN, EvalBackend, grade, load_cases, p95

pytestmark = [pytest.mark.live, pytest.mark.eval_bot]

REPORTS = Path(__file__).with_name("reports")
MIN_ACCURACY = 0.95
MAX_P95_SECONDS = 8.0


async def test_guide_eval() -> None:
    try:
        settings = load_settings(app_env="test")
    except ConfigError as exc:
        pytest.fail(f"live eval needs a real LLM configuration: {exc}")
    if settings.llm_provider == "fake":
        pytest.fail("live eval needs LLM_PROVIDER=gemini|openai and its API key")

    data = load_cases()
    backend = EvalBackend(data["kb"])
    app = create_app(
        settings,
        backend=BackendClient("http://backend", transport=httpx.MockTransport(backend)),
    )
    sources = backend.sources()
    rows, latencies = [], []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://eval", timeout=30
    ) as client:
        for case in data["cases"]:
            started = time.perf_counter()
            response = await client.post(
                "/api/v1/chat",
                json={"message": case["question"]},
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            seconds = time.perf_counter() - started
            latencies.append(seconds)
            body = response.json() if response.status_code == 200 else {}
            result = grade(case, body, sources)
            if response.status_code != 200:
                result.ok = False
                result.reasons.append(f"HTTP {response.status_code}")
            rows.append(
                {
                    "id": case["id"],
                    "lang": case["lang"],
                    "kind": case["kind"],
                    "ok": result.ok,
                    "reasons": result.reasons,
                    "seconds": round(seconds, 2),
                    "reply": body.get("reply"),
                    "tool_calls": (body.get("debug") or {}).get("tool_calls"),
                    "grounded": (body.get("debug") or {}).get("grounded"),
                }
            )

    passed = sum(r["ok"] for r in rows)
    accuracy = passed / len(rows)
    invented = [r["id"] for r in rows if any("not in the KB" in x for x in r["reasons"])]
    summary = {
        "provider": settings.llm_provider,
        "model": settings.gemini_model
        if settings.llm_provider == "gemini"
        else settings.openai_model,
        "cases": len(rows),
        "passed": passed,
        "accuracy": round(accuracy, 3),
        "invented": invented,
        "p95_seconds": round(p95(latencies), 2),
    }
    REPORTS.mkdir(exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    (REPORTS / f"guide-{stamp}.json").write_text(
        json.dumps({"summary": summary, "cases": rows}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    failures = "\n".join(f"  {r['id']}: {'; '.join(r['reasons'])}" for r in rows if not r["ok"])
    print(json.dumps(summary, ensure_ascii=False))

    assert not invented, f"invented facts in {invented}\n{failures}"
    assert accuracy >= MIN_ACCURACY, f"accuracy {accuracy:.0%} < 95%\n{failures}"
    assert summary["p95_seconds"] < MAX_P95_SECONDS, f"p95 {summary['p95_seconds']} s"
