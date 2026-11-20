import json
from collections.abc import Iterator

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import cli
from app.core.hotel_settings import load_hotel_settings
from app.modules.staff_auth.models import Staff, StaffRefreshToken
from app.modules.staff_auth.security import verify_password
from app.modules.stay_access.models import Room, RoomStatus, Stay, StayStatus
from tests.conftest import make_settings
from tests.factories import DEFAULT_PASSWORD, create_staff


def prompts(*answers: str) -> cli.PasswordPrompt:
    queue: Iterator[str] = iter(answers)
    return lambda _label: next(queue)


async def _run(
    *argv: str, prompt: cli.PasswordPrompt | None = None, env: str = "test"
) -> list[str]:
    printed: list[str] = []
    await cli.run(
        argv, settings=make_settings(app_env=env), prompt=prompt or prompts(), out=printed.append
    )
    return printed


async def _staff(db: AsyncSession, email: str) -> Staff:
    db.expire_all()
    staff = await db.scalar(select(Staff).where(Staff.email == email))
    assert staff is not None
    return staff


async def test_create_staff(db: AsyncSession) -> None:
    out = await _run(
        "create-staff",
        "--email",
        "Bep@Hotel.vn",
        "--name",
        "Bep Truong",
        "--role",
        "KITCHEN",
        prompt=prompts("kitchen-pass-123", "kitchen-pass-123"),
    )
    assert out == ["created bep@hotel.vn (KITCHEN)"]
    staff = await _staff(db, "bep@hotel.vn")
    assert staff.full_name == "Bep Truong"
    assert verify_password(staff.password_hash, "kitchen-pass-123")


@pytest.mark.parametrize(
    ("answers", "message"),
    [
        (("kitchen-pass-123", "different-pass"), "do not match"),
        (("short", "short"), "at least 10"),
        (("bep@hotel.vn", "bep@hotel.vn"), "must not equal the email"),
    ],
)
async def test_create_staff_rejects_bad_passwords(
    db: AsyncSession, answers: tuple[str, str], message: str
) -> None:
    with pytest.raises(cli.CliError, match=message):
        await _run(
            "create-staff",
            "--email",
            "bep@hotel.vn",
            "--name",
            "X",
            "--role",
            "KITCHEN",
            prompt=prompts(*answers),
        )


async def test_create_staff_refuses_duplicates(db: AsyncSession) -> None:
    await create_staff(db, email="bep@hotel.vn")
    with pytest.raises(cli.CliError, match="already exists"):
        await _run(
            "create-staff",
            "--email",
            "BEP@hotel.vn",
            "--name",
            "X",
            "--role",
            "KITCHEN",
            prompt=prompts("kitchen-pass-123", "kitchen-pass-123"),
        )


async def test_lock_signs_out_and_unlock_restores(
    db: AsyncSession, client: httpx.AsyncClient
) -> None:
    await create_staff(db)
    login = await client.post(
        "/api/v1/staff/auth/login",
        json={"email": "le.tan@hotel.test", "password": DEFAULT_PASSWORD},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert await _run("set-active", "--email", "le.tan@hotel.test", "--inactive") == [
        "le.tan@hotel.test is now locked"
    ]
    assert (await client.get("/api/v1/staff/me", headers=headers)).status_code == 401
    tokens = list(await db.scalars(select(StaffRefreshToken.revoked_at)))
    assert tokens and all(revoked is not None for revoked in tokens)

    await _run("set-active", "--email", "le.tan@hotel.test", "--active")
    assert (await _staff(db, "le.tan@hotel.test")).is_active


async def test_reset_password(db: AsyncSession) -> None:
    before = await create_staff(db)
    version = before.token_version
    out = await _run(
        "reset-password",
        "--email",
        "le.tan@hotel.test",
        prompt=prompts("a-new-password-1", "a-new-password-1"),
    )
    assert "existing sessions were signed out" in out[0]
    staff = await _staff(db, "le.tan@hotel.test")
    assert verify_password(staff.password_hash, "a-new-password-1")
    assert staff.token_version == version + 1


async def test_unknown_email(db: AsyncSession) -> None:
    with pytest.raises(cli.CliError, match="no staff account"):
        await _run("set-active", "--email", "ghost@hotel.vn", "--active")


async def test_seed_dev_only_in_dev(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_STAFF_PASSWORD", "dev-password-123")
    with pytest.raises(cli.CliError, match="APP_ENV=dev"):
        await _run("seed-dev", env="test")

    out = await _run("seed-dev", env="dev")
    assert out == ["created: reception@dev.local, kitchen@dev.local, housekeeping@dev.local"]
    assert await _run("seed-dev", env="dev") == ["created: nothing (already seeded)"]


async def test_seed_dev_needs_password(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEV_STAFF_PASSWORD", raising=False)
    with pytest.raises(cli.CliError, match="DEV_STAFF_PASSWORD"):
        await _run("seed-dev", env="dev")


def test_main_reports_errors_without_traceback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    assert cli.main(["seed-dev"]) == 1
    assert capsys.readouterr().err.startswith("error: missing required environment variable")


def test_password_is_not_an_argument() -> None:
    with pytest.raises(SystemExit):
        cli._parser().parse_args(
            [
                "create-staff",
                "--email",
                "a@b.c",
                "--name",
                "x",
                "--role",
                "KITCHEN",
                "--password",
                "p",
            ]
        )


async def test_reset_password_checks_the_account_before_prompting(db: AsyncSession) -> None:
    def no_prompt(_label: str) -> str:
        raise AssertionError("must not prompt for an unknown account")

    with pytest.raises(cli.CliError, match="no staff account"):
        await _run("reset-password", "--email", "ghost@hotel.vn", prompt=no_prompt)


async def test_seed_dev_stays_only_in_dev_and_after_seed_dev(db: AsyncSession) -> None:
    with pytest.raises(cli.CliError, match="APP_ENV=dev"):
        await _run("seed-dev-stays", env="test")
    with pytest.raises(cli.CliError, match="seed-dev first"):
        await _run("seed-dev-stays", env="dev")


async def test_seed_dev_stays_prints_working_tokens_and_cleans_up(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await create_staff(db, email=cli.DEV_RECEPTION)

    first = json.loads((await _run("seed-dev-stays", env="dev"))[0])
    assert [(s["label"], s["room_number"]) for s in first] == [("A", "DEV-A"), ("B", "DEV-B")]
    assert first[0]["stay_id"] != first[1]["stay_id"]
    for seeded in first:
        me = await client.get(
            "/api/v1/guest/me", headers={"Authorization": f"Bearer {seeded['token']}"}
        )
        assert me.status_code == 200
        assert me.json()["room_number"] == seeded["room_number"]

    # A second run starts from fresh stays: the previous ones are closed like a check-out.
    second = json.loads((await _run("seed-dev-stays", env="dev"))[0])
    old = await client.get(
        "/api/v1/guest/me", headers={"Authorization": f"Bearer {first[0]['token']}"}
    )
    assert old.status_code == 401
    new = await client.get(
        "/api/v1/guest/me", headers={"Authorization": f"Bearer {second[0]['token']}"}
    )
    assert new.status_code == 200

    assert await _run("seed-dev-stays", "--close", env="dev") == ["dev stays closed: 2"]
    db.expire_all()
    rooms = (await db.execute(select(Room.number, Room.status).order_by(Room.number))).all()
    assert rooms == [("DEV-A", RoomStatus.VACANT), ("DEV-B", RoomStatus.VACANT)]
    open_stays = await db.scalar(
        select(func.count()).select_from(Stay).where(Stay.status != StayStatus.CLOSED)
    )
    assert open_stays == 0
    assert await _run("seed-dev-stays", "--close", env="dev") == ["dev stays closed: 0"]


async def test_seed_dev_stays_count_for_the_load_test(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await create_staff(db, email=cli.DEV_RECEPTION)
    stays = json.loads((await _run("seed-dev-stays", "--count", "5", env="dev"))[0])
    assert [s["label"] for s in stays] == ["A", "B", "L003", "L004", "L005"]
    assert [s["room_number"] for s in stays][2:] == ["DEV-L003", "DEV-L004", "DEV-L005"]
    me = await client.get(
        "/api/v1/guest/me", headers={"Authorization": f"Bearer {stays[4]['token']}"}
    )
    assert me.status_code == 200 and me.json()["room_number"] == "DEV-L005"
    assert await _run("seed-dev-stays", "--close", env="dev") == ["dev stays closed: 5"]
    with pytest.raises(cli.CliError, match="between 1 and 200"):
        await _run("seed-dev-stays", "--count", "0", env="dev")


async def test_set_service_hours(db: AsyncSession) -> None:
    assert await _run("set-service-hours", "--open", "07:00", "--close", "21:30") == [
        "room service hours: 07:00-21:30"
    ]
    db.expire_all()
    settings = await load_hotel_settings(db)
    assert (settings.room_service_open.isoformat(), settings.room_service_close.isoformat()) == (
        "07:00:00",
        "21:30:00",
    )
    assert await _run("set-service-hours", "--open", "00:00", "--close", "00:00") == [
        "room service hours: around the clock"
    ]
    with pytest.raises(cli.CliError, match="not a time"):
        await _run("set-service-hours", "--open", "7h", "--close", "21:00")
