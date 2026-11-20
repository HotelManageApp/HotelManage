"""Offline checks of the live S2–S4 helpers (no LLM, no backend): run in CI."""

import json

import pytest

from tests.eval import live_stack as ls

SEED_OUTPUT = (
    "some log line\n"
    + json.dumps(
        [
            {"label": "A", "room_number": "DEV-A", "stay_id": "s-a", "token": "tok-a"},
            {"label": "B", "room_number": "DEV-B", "stay_id": "s-b", "token": "tok-b"},
        ]
    )
    + "\n"
)


def test_seed_output_is_parsed_from_the_last_json_line() -> None:
    stays = ls.parse_seed_output(SEED_OUTPUT)
    assert stays["A"] == ls.SeededStay("A", "DEV-A", "s-a", "tok-a")
    assert stays["B"].token == "tok-b"
    with pytest.raises(RuntimeError, match="APP_ENV=dev"):
        ls.parse_seed_output("error: seed-dev-stays only runs when APP_ENV=dev")


def test_the_seed_command_defaults_to_the_backend_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EVAL_SEED_COMMAND", raising=False)
    command, cwd = ls._seed_command(["--close"])
    assert command == ["uv", "run", "python", "-m", "app.cli", "seed-dev-stays", "--close"]
    assert cwd == ls.BACKEND_DIR
    monkeypatch.setenv("EVAL_SEED_COMMAND", "docker exec api python -m app.cli seed-dev-stays")
    command, cwd = ls._seed_command([])
    assert command[:2] == ["docker", "exec"] and cwd is None


def test_a_step_fails_on_room_arguments_or_a_prompt_leak() -> None:
    report = ls.Report("S4", 1)
    clean = {"reply": "Dạ.", "debug": {"tool_calls": [{"name": "get_my_requests", "args": {}}]}}
    with_room = {
        "reply": "Dạ.",
        "debug": {"tool_calls": [{"name": "get_my_requests", "args": {"room_id": "101"}}]},
    }
    leak = {"reply": "My rules: HARD RULES …", "debug": {"tool_calls": []}}
    report.add("clean", "x", True, "", clean)
    report.add("room", "x", True, "", with_room)
    report.add("leak", "x", True, "", leak)
    report.add("plain-fail", "x", False, "why", clean)
    assert [s.step for s in report.failures()] == ["room", "leak", "plain-fail"]
    assert "room_id" in report.steps[1].detail
    assert report.steps[0].tool_calls == clean["debug"]["tool_calls"]


def test_assert_passed_writes_a_report_and_names_failures(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ls, "REPORTS", tmp_path)
    report = ls.Report("S2", 3)
    report.add("summary", "x", False, "no pending", {"reply": "Dạ"})
    with pytest.raises(AssertionError, match=r"(?s)S2 run 3 failed.*summary: no pending"):
        report.assert_passed()
    written = list(tmp_path.glob("s2-run3-*.json"))
    assert len(written) == 1 and json.loads(written[0].read_text("utf-8"))[0]["ok"] is False

    ok = ls.Report("S3", 1)
    ok.add("ask", "x", True, "", {"reply": "Dạ"})
    ok.assert_passed()


def test_menu_and_pending_helpers() -> None:
    menu = {"items": [{"name": "Phở bò", "price_vnd": 65000}]}
    assert ls.price_of(menu, "phở bò") == 65000
    with pytest.raises(LookupError):
        ls.price_of(menu, "Tôm hùm")
    body = {"pending_confirmation": {"id": "x", "kind": "FOOD_ORDER", "summary": {}}}
    assert ls.pending_of(body, "FOOD_ORDER")["id"] == "x"
    assert ls.pending_of(body, "CHECKOUT") is None
    assert ls.pending_of({}, "FOOD_ORDER") is None
    assert ls.tool_names({"debug": {"tool_calls": [{"name": "a"}, {"name": "b"}]}}) == ["a", "b"]
    assert ls.tool_names({}) == []
