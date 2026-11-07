# Ingestion: reading from databases

`kind: ingest` nodes copy a table (or a query) from a database into the lake, with no
Python. The connections live in `sources.yaml`; credentials live in the environment.

## 1. Point the project at the sources file

```yaml
# ducta.yaml
settings:
  ingestion: {sources_path: sources.yaml}
```

## 2. Declare the connection (no credentials here)

```yaml
# sources.yaml
sources:
  shop_db:
    type: postgresql            # sqlserver | postgresql | mysql | mariadb | oracle | snowflake
    host: db.internal
    port: 5432
    database: shop
    description: Shop's production replica (read-only user)
```

`type`, `host`, `port` and `database` are required. Ducta downloads the JDBC driver for
the type into `lib/jdbc/` (under the directory Ducta runs from) the first time; a `driver:` block can pin it (for
example a `sha256`). `url_params` adds JDBC URL parameters (SQL Server is encrypted by
default and its certificate is verified; for a self-signed one set
`trustServerCertificate: "true"`. PostgreSQL, MySQL and MariaDB get the same check, with
`sslmode: verify-full` / `sslMode: VERIFY_IDENTITY`, whenever the host is not `localhost`; a server
without a certificate needs `sslmode: require` / `sslMode: REQUIRED`, or `disable` / `DISABLED` to
turn TLS off). `host` is a host name or address only and `database` uses
letters, digits and `_ $ . -`: a port, a `?`, `;` or `&` in either is refused, because it would add
parameters to the connection URL.

## 3. Credentials: environment variables or `.env`

For a source named `shop_db`, Ducta reads:

```bash
SHOP_DB_USER=reader
SHOP_DB_PASSWORD=…
```

from the process environment first and then the project's `.env` (never commit it).

**As an assistant:** never write the password into a file yourself and never ask the
user to paste it into the chat. Tell the user which two variable names to set, and
where (`.env` or their shell).

`ducta init ingestion setup` is an **interactive** wizard that writes the connection
and the `.env` entries. It needs a terminal: ask the user to run it themselves, or
write `sources.yaml` as above and let them fill `.env`.

## 4. Check the connection

```bash
ducta init ingestion list
ducta init ingestion info --source shop_db
ducta init ingestion test --source shop_db
```

`test` exits 0 when the connection answered, 4 when it failed, and 5 when it could
not be tried: testing needs a Spark session, which the CLI does not start. Exit 5 is
not a failure — tell the user the first run of an ingest node will check it.

## 5. The ingest node

```yaml
# pipelines/bronze.shop.yaml
requires_dates: false
nodes:
  land_orders:
    kind: ingest
    ingest:
      source: shop_db
      table: public.orders          # or: query: "SELECT … FROM …"
      columns: [order_id, amount, order_date]
      where: "order_date >= '2026-01-01'"
      options: {fetchsize: 10000}   # passed to the JDBC reader
    outputs: [bronze.shop.orders]
```

Declare `bronze.shop.orders` in the catalog. An ingest node accepts only its own keys
(no `run:`, no `inputs:`).

To load by day (or month) instead of the whole table, add `incremental: {column: order_ts}`
to `ingest:` and run with `--start-date`/`--end-date`: the database filters
`order_ts >= start AND order_ts < end + 1 day` and returns only that window. Pair it with a
write that re-runs safely (`partition_overwrite: dynamic`, or Delta `merge`/`replaceWhere`).
For year/month partition columns use a `query` that computes them.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Credentials missing for a source (no user/password) | Set both variables (name = source name upper-cased), or add them to `.env`. |
| Driver download fails | No internet from that machine: put the driver JAR in `lib/jdbc/` yourself, or pin it under `driver:`. |
| TLS / certificate errors (SQL Server; PostgreSQL, MySQL, MariaDB on a non-local host) | The server's certificate is verified by default. Install one the JVM trusts, or for a dev server set `url_params` to `trustServerCertificate: "true"` (SQL Server), `sslmode: require` (PostgreSQL) or `sslMode: REQUIRED` (MySQL, MariaDB). Ducta warns: the connection is then encrypted but not authenticated. |
| `Invalid host` / `Invalid database` | `host` is the name or IP only (no `:port`, no path); `database` has no `?`, `;`, `&`, `=` or spaces. Put the port in `port` and driver options in `url_params`. |
| `${DB_PASSWORD}` refused in YAML | By design: secret-looking variables cannot be interpolated into configuration. Use the `<SOURCE>_PASSWORD` convention. |
| Connection refused / timeout | `ducta init ingestion test --source NAME`; check host, port, firewall, VPN. |
