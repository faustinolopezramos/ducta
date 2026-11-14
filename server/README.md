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
`--db <sqlite file>` and `--allow-unauthenticated`. Run `ducta-server --help`.

On an address other than this machine's, the server refuses to start without
authentication (`AUTH_ENABLED=true` and a `JWT_SECRET_KEY`): it runs pipelines,
so reaching it is reaching code execution.

Documentation: <https://github.com/faustinolopezramos/ducta/tree/main/docs>
(see *Server & API* and *Deployment*). License: Apache-2.0.
