"""
Copyright (C) 2024-2026 Faustino Lopez Ramos

This file is part of ducta.

Licensed under the Apache License, Version 2.0 (the "License"); you may not
use this file except in compliance with the License. You may obtain a copy
of the License at

    https://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations
under the License.

SPDX-License-Identifier: Apache-2.0

``ducta-server``: start Ducta's web server — the API and the web app on one port.

The same server ``ducta ui`` starts when both packages are installed; this
command needs only this one (which installs Ducta's engine with it).

``ducta-server user …`` manages the accounts that may sign in (the web app has no screen
for them): ``add``, ``list``, ``set-role``, ``set-password``, ``disable``, ``enable``.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable, List, Optional

from loguru import logger

from ducta.console.parser import add_server_options


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ducta-server",
        description="Start Ducta's web server: the API and the web app, on one port.",
    )
    parser.add_argument("--version", action="store_true", help="Print the version and exit")
    add_server_options(parser)
    return parser


def build_user_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ducta-server user",
        description=(
            "Manage the accounts that may sign in. They live in the server's database "
            "(SQLite by default, PostgreSQL with DATABASE_URL). Roles: admin, developer, "
            "operator, viewer."
        ),
    )
    parser.add_argument(
        "--db",
        dest="db_path",
        default=None,
        help="SQLite database (default: ~/.ducta/executions.db; DATABASE_URL wins if set)",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    def with_password(p: argparse.ArgumentParser) -> None:
        p.add_argument(
            "--password-env",
            metavar="VAR",
            help="Read the password from this environment variable (default: ask, twice)",
        )

    add = commands.add_parser("add", help="Create a user")
    add.add_argument("username")
    add.add_argument("--role", dest="roles", action="append", help="Role (repeat for several)")
    add.add_argument("--email", help="Email (default: <username>@ducta.local)")
    with_password(add)
    commands.add_parser("list", help="List users, their roles and whether they are active")
    role = commands.add_parser("set-role", help="Replace a user's roles")
    role.add_argument("username")
    role.add_argument("roles", nargs="+", help="Role names")
    passwd = commands.add_parser("set-password", help="Change a user's password")
    passwd.add_argument("username")
    with_password(passwd)
    for name, text in (("disable", "Refuse a user's logins"), ("enable", "Allow it again")):
        commands.add_parser(name, help=text).add_argument("username")
    return parser


def _read_password(args: argparse.Namespace) -> str:
    """The password from ``--password-env`` or typed twice; never from an argument."""
    if args.password_env:
        value = os.environ.get(args.password_env)
        if not value:
            raise SystemExit(f"ducta-server: environment variable {args.password_env} is not set")
        return value
    if not sys.stdin.isatty():
        raise SystemExit("ducta-server: no terminal to ask the password on: use --password-env VAR")
    first = getpass.getpass("Password: ")
    if first != getpass.getpass("Repeat it: "):
        raise SystemExit("ducta-server: the passwords differ")
    return first


async def _with_store(work: Callable[[Any], Awaitable[int]]) -> int:
    from ducta_server.db.engine import get_engine
    from ducta_server.db.migrate import run_migrations
    from ducta_server.db.stores.user_store import get_db_user_store

    engine = get_engine()
    if engine is None:
        raise SystemExit("ducta-server: no database is configured: set DATABASE_URL or pass --db")
    try:
        await run_migrations(engine)
        return await work(get_db_user_store())
    finally:
        await engine.dispose()
        # One command, one engine: nothing cached for whoever runs the next one in this process.
        from ducta_server.db import engine as engine_module
        from ducta_server.db import migrate as migrate_module
        from ducta_server.db import session as session_module

        engine_module._engine = None
        session_module._session_factory = None
        migrate_module._migrations_run = False


def user_main(argv: List[str]) -> int:
    """``ducta-server user …``. Returns the exit code (2: refused, with the reason)."""
    args = build_user_parser().parse_args(argv)
    if "DATABASE_URL" not in os.environ:
        from ducta_server.launcher import _DEFAULT_DB_PATH

        db = Path(args.db_path) if args.db_path else _DEFAULT_DB_PATH
        db.parent.mkdir(parents=True, exist_ok=True)
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db}"
    from ducta_server.config import get_settings
    from ducta_server.db.stores.user_store import UserAdminError

    get_settings.cache_clear()
    logger.remove()  # the command's answer is its output, not the server's log

    async def work(store: Any) -> int:
        if args.command == "list":
            for u in await store.list_users():
                state = "active" if u.is_active else "disabled"
                print(f"{u.username:<20} {','.join(u.roles):<28} {state:<9} {u.email}")
            return 0
        if args.command == "add":
            user = await store.create_user(
                args.username, _read_password(args), args.roles or ["viewer"], args.email
            )
            print(f"Created {user.username} ({', '.join(user.roles)}).")
        elif args.command == "set-role":
            user = await store.set_roles(args.username, args.roles)
            print(f"{user.username} is now {', '.join(user.roles)}.")
        elif args.command == "set-password":
            user = await store.set_password(args.username, _read_password(args))
            print(f"Changed the password of {user.username}.")
        else:
            user = await store.set_active(args.username, args.command == "enable")
            print(f"{user.username} is {'active' if user.is_active else 'disabled'}.")
        return 0

    try:
        return asyncio.run(_with_store(work))
    except UserAdminError as exc:
        print(f"ducta-server: {exc}", file=sys.stderr)
        return 2


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["user"]:
        return user_main(argv[1:])
    args = build_parser().parse_args(argv)
    if args.version:
        from ducta_server import __version__

        print(f"ducta-server {__version__}")
        return 0
    from ducta_server.launcher import launch_ui

    return int(
        launch_ui(
            host=args.host,
            port=args.port,
            open_browser=not args.no_browser,
            source=args.source,
            db_path=args.db_path,
            allow_unauthenticated=args.allow_unauthenticated,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
