# ducta-server

Ducta's web server: the REST/WebSocket API and the web app, on one port.

[Ducta](https://github.com/faustinolopezramos/ducta) is a configuration-as-code
framework for batch, streaming, ML and hybrid data pipelines. It comes in two
packages, from the same repository and always at the same version:

| You want… | Install | Then |
|---|---|---|
| The command line only | `pip install ducta` | `ducta start`, `ducta check`… |
| The web app | `pip install ducta-server` | `ducta-server` |
| Both | `pip install ducta ducta-server` | both; `ducta ui` starts the web app too |

`ducta-server` installs `ducta` (the engine that runs your pipelines) with it.
Add the engine's extras the same way you would without the server, for example
Spark and the AI assistant:

```bash
pip install ducta-server "ducta[spark,ai]"
ducta-server            # http://127.0.0.1:8000, opens a browser
```

Options: `--host`, `--port`, `--no-browser`, `--source <workspace>`,
`--db <sqlite file>`, `--allow-unauthenticated` and `--version`. Run
`ducta-server --help`.

## On your machine

Bound to `127.0.0.1` (the default) the server needs no login: every request runs as
a local admin. Nothing more to set up.

## Shared with a team

The server runs pipelines, so reaching it is reaching code execution. On an address
other than this machine's it refuses to start unless accounts are on and their
credentials are your own:

```bash
export AUTH_ENABLED=true
export JWT_SECRET_KEY="$(openssl rand -hex 32)"
export DUCTA_ADMIN_PASSWORD="…"                       # the admin account's password
export DATABASE_URL="postgresql+asyncpg://user:pass@db:5432/ducta"
ducta-server --host 0.0.0.0 --no-browser

ducta-server user add ana --role developer           # then manage accounts
ducta-server user list
```

- **Roles**: `viewer` reads; `developer` edits and runs outside protected environments;
  `operator` runs what is there, production included; `admin` does everything,
  including promoting models to Production.
- **Production data** (`prod`/`production` by default, and whatever
  `DUCTA_PROTECTED_ENVIRONMENTS` adds) is out of a developer's reach: its rows, files
  and runs. Columns listed in `metadata.pii` read `••••` for roles without access to
  personal data. Every read of either is audited.
- **PostgreSQL for accounts.** Runs execute as the server's OS user and could rewrite
  a SQLite accounts file, so a shared server refuses SQLite unless
  `ALLOW_SQLITE_WITH_ACCOUNTS=true` (every developer trusted as admin).

Upgrading from `0.3.0`: do it for any server others can reach — see
[SECURITY.md](https://github.com/faustinolopezramos/ducta/blob/main/SECURITY.md) and the
[CHANGELOG](https://github.com/faustinolopezramos/ducta/blob/main/CHANGELOG.md).

Documentation: <https://github.com/faustinolopezramos/ducta/tree/main/docs>
(see *Server & API* and *Deployment*). License: Apache-2.0.
