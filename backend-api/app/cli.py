"""Admin CLI: `uv run python -m app.cli <command> ...` (spec/SPEC-staff-auth.md, "CLI quản trị").

Passwords are only ever read from a hidden prompt (or DEV_STAFF_PASSWORD for seed-dev), never from
command-line arguments, so they do not end up in shell history or process lists.
"""

import argparse
import asyncio
import csv
import getpass
import io
import os
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import ConfigError, Settings, load_settings
from app.core.db import create_engine, create_sessionmaker
from app.modules.room_service.models import MenuCategory, MenuItem
from app.modules.staff_auth import repository
from app.modules.staff_auth.models import Staff, StaffRole
from app.modules.staff_auth.schemas import MIN_PASSWORD_LENGTH
from app.modules.staff_auth.security import hash_password
from app.modules.stay_access import repository as stay_repository
from app.modules.stay_access.models import Room

PasswordPrompt = Callable[[str], str]

DEV_STAFF = (
    ("reception@dev.local", "Le Tan (dev)", StaffRole.RECEPTION),
    ("kitchen@dev.local", "Bep (dev)", StaffRole.KITCHEN),
    ("housekeeping@dev.local", "Buong Phong (dev)", StaffRole.HOUSEKEEPING),
)


class CliError(Exception):
    """A problem the operator can fix; printed without a traceback."""


def _validate_password(password: str, email: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise CliError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if password.lower() == email.lower():
        raise CliError("password must not equal the email")


def _ask_new_password(prompt: PasswordPrompt, email: str) -> str:
    first = prompt("New password: ")
    if prompt("Repeat password: ") != first:
        raise CliError("passwords do not match")
    _validate_password(first, email)
    return first


async def _require_staff(db: AsyncSession, email: str) -> Staff:
    staff = await repository.get_staff_by_email(db, email.lower())
    if staff is None:
        raise CliError(f"no staff account with email {email}")
    return staff


async def create_staff(
    db: AsyncSession, *, email: str, name: str, role: StaffRole, password: str
) -> Staff:
    email = email.lower()
    if "@" not in email:
        raise CliError("email must contain @")
    if await repository.get_staff_by_email(db, email) is not None:
        raise CliError(f"a staff account with email {email} already exists")
    _validate_password(password, email)
    staff = Staff(email=email, full_name=name, role=role, password_hash=hash_password(password))
    db.add(staff)
    await db.commit()
    return staff


async def set_active(db: AsyncSession, *, email: str, active: bool) -> Staff:
    staff = await _require_staff(db, email)
    staff.is_active = active
    if not active:
        staff.token_version += 1
        await repository.revoke_all_for_staff(db, staff.id, datetime.now(UTC))
    await db.commit()
    return staff


async def reset_password(db: AsyncSession, *, email: str, password: str) -> Staff:
    staff = await _require_staff(db, email)
    _validate_password(password, staff.email)
    staff.password_hash = hash_password(password)
    staff.token_version += 1
    await repository.revoke_all_for_staff(db, staff.id, datetime.now(UTC))
    await db.commit()
    return staff


async def seed_dev(db: AsyncSession, settings: Settings, *, password: str | None) -> list[str]:
    if settings.app_env != "dev":
        raise CliError("seed-dev only runs when APP_ENV=dev")
    if not password:
        raise CliError("set DEV_STAFF_PASSWORD to the password for the dev accounts")
    created = []
    for email, name, role in DEV_STAFF:
        if await repository.get_staff_by_email(db, email) is None:
            await create_staff(db, email=email, name=name, role=role, password=password)
            created.append(email)
    return created


async def seed_rooms(db: AsyncSession, path: Path) -> tuple[int, int]:
    """Create rooms from a CSV (number,floor,room_type). Existing numbers are left untouched."""
    try:
        content = await asyncio.to_thread(path.read_text, encoding="utf-8-sig")
    except FileNotFoundError:
        raise CliError(f"file not found: {path}") from None
    created = skipped = 0
    for line, row in enumerate(csv.DictReader(io.StringIO(content)), start=2):
        number = (row.get("number") or "").strip()
        if not number:
            raise CliError(f"line {line}: number is required")
        floor_raw = (row.get("floor") or "").strip()
        try:
            floor = int(floor_raw) if floor_raw else None
        except ValueError:
            raise CliError(f"line {line}: floor must be a number") from None
        if await stay_repository.get_room_by_number(db, number) is not None:
            skipped += 1
            continue
        db.add(Room(number=number, floor=floor, room_type=(row.get("room_type") or None)))
        await db.flush()
        created += 1
    await db.commit()
    return created, skipped


async def seed_menu(db: AsyncSession, path: Path) -> tuple[int, int]:
    """Create categories and dishes from a CSV. Columns: category_code, category_vi, category_en,
    name_vi, name_en, price_vnd, description_vi, description_en. Existing dishes (same category
    and Vietnamese name) are left untouched."""
    try:
        content = await asyncio.to_thread(path.read_text, encoding="utf-8-sig")
    except FileNotFoundError:
        raise CliError(f"file not found: {path}") from None
    created = skipped = 0
    categories: dict[str, MenuCategory] = {}
    for line, row in enumerate(csv.DictReader(io.StringIO(content)), start=2):
        code = (row.get("category_code") or "").strip().upper()
        name_vi = (row.get("name_vi") or "").strip()
        if not code or not name_vi:
            raise CliError(f"line {line}: category_code and name_vi are required")
        try:
            price = int((row.get("price_vnd") or "").replace(".", "").replace(",", ""))
        except ValueError:
            raise CliError(f"line {line}: price_vnd must be a whole number") from None
        category = categories.get(code) or await db.scalar(
            select(MenuCategory).where(MenuCategory.code == code)
        )
        if category is None:
            category = MenuCategory(
                code=code,
                name_vi=(row.get("category_vi") or code).strip(),
                name_en=(row.get("category_en") or code).strip(),
                sort_order=len(categories),
            )
            db.add(category)
            await db.flush()
        categories[code] = category
        exists = await db.scalar(
            select(MenuItem.id).where(
                MenuItem.category_id == category.id, MenuItem.name_vi == name_vi
            )
        )
        if exists:
            skipped += 1
            continue
        db.add(
            MenuItem(
                category_id=category.id,
                name_vi=name_vi,
                name_en=(row.get("name_en") or name_vi).strip(),
                description_vi=(row.get("description_vi") or None),
                description_en=(row.get("description_en") or None),
                price_vnd=price,
            )
        )
        await db.flush()
        created += 1
    await db.commit()
    return created, skipped


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create-staff", help="create a staff account")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", required=True, choices=[r.value for r in StaffRole])

    active = commands.add_parser("set-active", help="lock or unlock an account")
    active.add_argument("--email", required=True)
    toggle = active.add_mutually_exclusive_group(required=True)
    toggle.add_argument("--active", dest="active", action="store_true")
    toggle.add_argument("--inactive", dest="active", action="store_false")

    reset = commands.add_parser("reset-password", help="set a new password")
    reset.add_argument("--email", required=True)

    commands.add_parser("seed-dev", help="create the three dev accounts (APP_ENV=dev only)")

    rooms = commands.add_parser("seed-rooms", help="create rooms from a CSV file")
    rooms.add_argument("--from-file", required=True, type=Path)

    menu = commands.add_parser("seed-menu", help="create menu categories and dishes from a CSV")
    menu.add_argument("--from-file", required=True, type=Path)
    return parser


async def run(
    argv: Sequence[str],
    *,
    settings: Settings,
    prompt: PasswordPrompt = getpass.getpass,
    out: Callable[[str], None] = print,
) -> None:
    args = _parser().parse_args(argv)
    engine = create_engine(settings)
    try:
        async with create_sessionmaker(engine)() as db:
            if args.command == "create-staff":
                password = _ask_new_password(prompt, args.email)
                staff = await create_staff(
                    db,
                    email=args.email,
                    name=args.name,
                    role=StaffRole(args.role),
                    password=password,
                )
                out(f"created {staff.email} ({staff.role.value})")
            elif args.command == "set-active":
                staff = await set_active(db, email=args.email, active=args.active)
                out(f"{staff.email} is now {'active' if staff.is_active else 'locked'}")
            elif args.command == "reset-password":
                await _require_staff(db, args.email)  # fail before asking for a password
                password = _ask_new_password(prompt, args.email)
                staff = await reset_password(db, email=args.email, password=password)
                out(f"password reset for {staff.email}; existing sessions were signed out")
            elif args.command == "seed-dev":
                created = await seed_dev(
                    db, settings, password=os.environ.get("DEV_STAFF_PASSWORD")
                )
                out("created: " + (", ".join(created) if created else "nothing (already seeded)"))
            elif args.command == "seed-rooms":
                made, skipped = await seed_rooms(db, args.from_file)
                out(f"rooms created: {made}, already existed: {skipped}")
            elif args.command == "seed-menu":
                made, skipped = await seed_menu(db, args.from_file)
                out(f"dishes created: {made}, already existed: {skipped}")
    finally:
        await engine.dispose()


def main(argv: Sequence[str] | None = None) -> int:
    try:
        settings = load_settings()
        asyncio.run(run(sys.argv[1:] if argv is None else argv, settings=settings))
    except (CliError, ConfigError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
