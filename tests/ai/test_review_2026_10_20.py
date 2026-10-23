"""The 2026-10-20 review of ``ducta.ai`` and the skill: an extension cannot rebind what
a module already has; a credential is seen inside a connection string, a key or a token;
a broken connection is an ``AIError``; ``new`` and ``fix`` code gets the review an
extension's gets; the scanners stay linear on long text."""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from ducta.ai.agents.architect.blueprint import PipelineSpec
from ducta.ai.agents.architect.build import module_problems
from ducta.ai.builder import fix, generate
from ducta.ai.config import AIConfig, build_config
from ducta.ai.context import find_secrets, redact, redact_code
from ducta.ai.errors import AIConfigError, AIError
from ducta.ai.explain import _code_around
from ducta.ai.extend import _module_changes, existing_changes, new_code_problems
from ducta.ai.providers import ChatMessage, OllamaProvider, OpenAICompatibleProvider
from ducta.ai.review import ReviewFacts, _code_findings

sys.path.insert(0, str(Path(__file__).parent))
from test_builder import GOOD, FakeProvider, _project  # noqa: E402

SALES = (
    Path(__file__).parents[2]
    / "src"
    / "ducta"
    / "skills"
    / "ducta"
    / "assets"
    / "examples"
    / "sales"
)
BEFORE = "import pandas as pd\nCONFIG = {'a': 1}\n\n\ndef clean(df):\n    return df.dropna()\n"


# ── an extension adds; it does not rebind ───────────────────────────────────


@pytest.mark.parametrize(
    "added",
    [
        "\n\ndef clean(df):\n    return df.head(0)\n",
        "\n\nclean = lambda df: df.head(0)\n",
        "\n\nfrom other import helper as clean\n",
        "\n\nclass clean:\n    pass\n",
        "\n\nCONFIG = {'a': 2}\n",
        "\n\nCONFIG['a'] = 2\n",
        "\n\nclean.__code__ = None\n",
        "\n\nif True:\n    clean = None\n",
        "\n\nwith open('x') as pd:\n    pass\n",
    ],
)
def test_a_name_the_module_has_cannot_be_bound_again(added):
    found = _module_changes("m.py", BEFORE, BEFORE + added)
    assert found and "already exist" in found[0]


@pytest.mark.parametrize(
    "added",
    [
        "\n\ndef latest(df):\n    return df.tail(1)\n",
        "\n\nimport pandas as pd\n",  # the same import again
        "\n\nimport numpy as np\n\nLIMIT = 3\n",
        "\n\n__all__ = ['clean', 'latest']\n",
    ],
)
def test_new_names_and_the_same_import_are_additions(added):
    assert _module_changes("m.py", BEFORE, BEFORE + added) == []


def test_a_module_that_loses_a_statement_is_still_reported():
    found = _module_changes("m.py", BEFORE, BEFORE.replace("return df.dropna()", "return df"))
    assert found and "clean()" in found[0] and "changed or is missing" in found[0]


def test_a_redefined_function_is_refused_for_a_whole_extension(tmp_path):
    root = tmp_path / "sales"
    shutil.copytree(SALES, root)
    pipe = (root / "pipelines" / "silver.sales.yaml").read_text()
    module = (root / "pipelines" / "sales.py").read_text()
    new_pipe = pipe.rstrip("\n") + (
        "\n  latest_customers:\n    description: x\n    run: pipelines.sales:latest_customers\n"
        "    inputs: {orders: silver.sales.orders}\n    outputs: [silver.sales.customers]\n"
    )
    sneaky = (
        module
        + "\n\ndef clean_orders(*a, **k):\n    return None\n\n\n"
        + "def latest_customers(orders, **kwargs):\n    return orders\n"
    )
    files = {"pipelines/silver.sales.yaml": new_pipe, "pipelines/sales.py": sneaky}
    found = existing_changes(root, "silver.sales", files)
    assert found and "clean_orders" in found[0]


# ── credentials inside texts, keys and tokens ───────────────────────────────

SECRET_PY = {
    "jdbc": 'URL = "jdbc:sqlserver://h:1433;databaseName=d;user=u;password=Hunter2xx;"\n',
    "odbc": "conn = 'DRIVER={x};SERVER=h;UID=u;PWD=Hunter2xx'\n",
    "libpq": "dsn = 'host=h dbname=d user=u password=Hunter2xx'\n",
    "short": "password = 'abc12'\n",
    "pem": "k = '''-----BEGIN RSA PRIVATE KEY-----\nMIIEvQIBADANBgkq\n-----END RSA PRIVATE KEY-----'''\n",
    "jwt": "t = 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0In0.abcdefghijk'\n",
    "comment": "# password=Hunter2xx\n",
}
SECRET_YAML = {
    "quoted": 'url: "jdbc:sqlserver://h;user=u;password=Hunter2xx"\n',
    "bare": "url: jdbc:sqlserver://h;user=u;password=Hunter2xx\n",
    "list": "options:\n  - password=Hunter2xx\n",
    "sas": "path: abfss://c@acct.dfs.core.windows.net/x?sv=1&sig=AbCdEf123456\n",
}


@pytest.mark.parametrize("text", SECRET_PY.values(), ids=SECRET_PY)
def test_python_credentials_are_seen_and_masked(text):
    assert find_secrets(text)
    masked = redact_code(text)
    assert "Hunter2xx" not in masked and "abc12" not in masked and "MIIEvQ" not in masked
    assert "abcdefghijk" not in masked
    assert not find_secrets(masked)


@pytest.mark.parametrize("text", SECRET_YAML.values(), ids=SECRET_YAML)
def test_yaml_credentials_are_seen_and_masked(text):
    assert find_secrets(text, yaml=True)
    masked = redact_code(text, yaml=True)
    assert "Hunter2xx" not in masked and "AbCdEf123456" not in masked
    assert not find_secrets(masked, yaml=True)


@pytest.mark.parametrize(
    "text",
    [
        "conn = connect(host, password=os.environ['DB_PASSWORD'])\n",
        "def login(user, password=None):\n    return connect(user, password=password)\n",
        "token_url = 'https://login.example.com/token'\n",
        "max_tokens = 4000\n",
        "headers = {'Authorization': f'Bearer {token}'}\n",
        "url = f'postgresql://u:{password}@h/db'\n",
        "query = 'select * from t where a=1 and b=2'\n",
        "password = '${DB_PASSWORD}'\n",
        "sig = 'x'\n",
    ],
)
def test_code_that_only_uses_a_credential_is_not_one(text):
    assert find_secrets(text) == []


def test_yaml_that_names_a_variable_is_not_a_credential():
    assert (
        find_secrets("password: ${DB_PASSWORD}\nurl: jdbc:x://h;password=${PW}\n", yaml=True) == []
    )


@pytest.mark.parametrize("unit", ["a_", "ab.c-", "http", "a:/", "a=", "x" * 40 + " "])
def test_the_scanners_stay_linear_on_long_text(unit):
    text = unit * (400_000 // len(unit))
    started = time.perf_counter()
    redact(text)
    find_secrets(text)
    find_secrets(text, yaml=True)
    # Quadratic, 400 KB of these took minutes; linear is well under a second.
    assert time.perf_counter() - started < 5


@pytest.mark.parametrize(
    "text, secret",
    [
        ("db_password=abc12345", "abc12345"),
        ("PGPASSWORD=abc12345", "abc12345"),
        ("AWS_SECRET_ACCESS_KEY=abc12345", "abc12345"),
        ("fs.s3a.secret.key=abc12345", "abc12345"),
        ("jdbc:postgresql://u:hunter2@h/db", "hunter2"),
        ("Authorization: Basic abcdef12", "abcdef12"),
    ],
)
def test_redact_still_masks_what_it_masked(text, secret):
    assert secret not in redact(text)


def test_redact_keeps_what_is_not_a_credential():
    assert redact("max_tokens=5000 assigned=3") == "max_tokens=5000 assigned=3"


# ── a connection that breaks is an AIError ──────────────────────────────────


def _failing(exc):
    def handler(request):
        raise exc

    return httpx.Client(transport=httpx.MockTransport(handler), base_url="http://localhost:1/v1")


@pytest.mark.parametrize(
    "exc",
    [
        httpx.RemoteProtocolError("Server disconnected without sending a response"),
        httpx.ReadError("connection reset"),
        httpx.WriteError("broken pipe"),
        httpx.ProxyError("proxy"),
        httpx.UnsupportedProtocol("bad scheme"),
        httpx.InvalidURL("bad url"),
    ],
    ids=lambda e: type(e).__name__,
)
@pytest.mark.parametrize("kind", [OpenAICompatibleProvider, OllamaProvider])
def test_a_broken_connection_says_what_to_do(kind, exc):
    provider_name = "ollama" if kind is OllamaProvider else "openai_compatible"
    config = build_config(provider_name, model="m", base_url="http://localhost:1/v1")
    provider = kind(config, None, client=_failing(exc))
    with pytest.raises(AIError, match="connection to .* failed") as raised:
        provider.complete("system", [ChatMessage("user", "hi")])
    assert type(exc).__name__ in raised.value.message
    assert "try again" in raised.value.message


# ── new and fix drafts are reviewed like an extension ───────────────────────

RISKY_NEW = GOOD.replace(
    "def totals(orders, **kwargs):\n    return orders",
    "import subprocess\n\n\ndef totals(orders, **kwargs):\n    subprocess.run(['ls'])\n    return orders",
)


def test_a_new_draft_that_runs_commands_is_sent_back(tmp_path):
    root = _project(tmp_path)
    draft = generate(root, "totals", FakeProvider(RISKY_NEW), max_attempts=1)
    assert not draft.ok
    assert any("runs commands" in p["message"] for p in draft.blocking)


def test_a_new_draft_that_is_clean_still_passes(tmp_path):
    root = _project(tmp_path)
    assert generate(root, "totals", FakeProvider(GOOD)).ok


def test_a_fix_is_not_asked_to_remove_the_reads_it_already_had(tmp_path):
    root = _project(tmp_path)
    old = "import pandas as pd\n\n\ndef clean(df, **kwargs):\n    ref = pd.read_csv('ref.csv')\n    return df\n"
    (root / "src" / "m.py").write_text(old)
    renamed = old.replace("(df, **kwargs)", "(orders, **kwargs)").replace(
        "return df", "return orders"
    )
    assert new_code_problems(root, {"src/m.py": renamed}) == []
    added = renamed.replace("ref.csv", "other.csv")
    assert any("reads files itself" in p for p in new_code_problems(root, {"src/m.py": added}))


def test_a_fix_with_a_new_command_is_sent_back(tmp_path):
    root = _project(tmp_path)
    (root / "src" / "m.py").write_text("def clean(df, x=1):\n    return df\n")
    answer = (
        "```python file=src/m.py\nimport subprocess\n\n\ndef clean(orders, **kwargs):\n"
        "    subprocess.run(['ls'])\n    return orders\n```"
    )
    draft = fix(root, "etl", FakeProvider(answer), note="rename the parameter", max_attempts=1)
    assert not draft.ok
    assert any("runs commands" in p["message"] for p in draft.blocking)


# ── what the static review sees ─────────────────────────────────────────────


def _flags(code: str):
    facts = ReviewFacts("", "", "", "dev", {}, {}, {})
    facts.function = {"file": "m.py", "line": 1, "function": "f"}
    facts.code_lines = code.splitlines()
    return [f.title for f in _code_findings(facts)]


@pytest.mark.parametrize(
    "code",
    [
        "def f(df):\n    df.to_sql('t', con)\n    return df",
        "def f(df):\n    df.to_sql(name='t', con=con)\n    return df",
        "def f(df):\n    df.to_pickle('x.pkl')\n    return df",
        "import pandas as pd\ndef f(df):\n    return pd.read_sql_query('select 1', con)",
        "import pandas as pd\ndef f(df):\n    return pd.read_pickle('x')",
        "from pandas import read_sql_query as q\ndef f(df):\n    return q('select 1', con)",
        "import os as o\ndef f(df):\n    o.system('x')\n    return df",
        "from os import system\ndef f(df):\n    system('x')\n    return df",
        "from os import system as run\ndef f(df):\n    run('x')\n    return df",
        "import importlib\ndef f(df):\n    importlib.import_module('subprocess')\n    return df",
        "import shutil\ndef f(df):\n    shutil.move('a', 'b')\n    return df",
        "import pickle\ndef f(df):\n    return pickle.loads(b'x')",
        "def f(df):\n    return spark.table('db.t')",
        "def f(self):\n    return self.spark.read.parquet('x')",
        "def f(df):\n    return sparkSession.readStream.format('kafka').load()",
    ],
)
def test_the_review_sees_what_a_node_should_not_do(code):
    assert _flags(code), code


@pytest.mark.parametrize(
    "code",
    [
        "def f(df):\n    return df.to_json()",
        "def f(df):\n    return df.to_csv(index=False)",
        "def f(df, F):\n    return df.withColumn('a', F.col('b'))",
        "def f(df):\n    table = df.table\n    return df.groupBy('a')",
    ],
)
def test_the_review_leaves_ordinary_code_alone(code):
    assert _flags(code) == []


# ── Architect: a required keyword-only parameter ────────────────────────────


def test_architect_refuses_a_required_keyword_only_parameter():
    from ducta.ai.agents.architect.blueprint import NodeSpec

    pipe = PipelineSpec(
        name="silver.x",
        nodes={"n": NodeSpec(name="n", inputs={"orders": "bronze.a.b"}, outputs=["silver.a.c"])},
    )
    ok = "def n(orders, **kwargs):\n    return orders\n"
    bad = "def n(orders, *, mode, **kwargs):\n    return orders\n"
    assert module_problems(ok, "src/x.py", pipe) == []
    assert any("also requires mode" in p for p in module_problems(bad, "src/x.py", pipe))


# ── configuration limits ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "changes",
    [{"max_attempts": 500}, {"timeout_seconds": 1e9}, {"context_tokens": 10**12}],
)
def test_absurd_limits_are_an_error(changes):
    with pytest.raises(AIConfigError):
        AIConfig(
            provider="ollama", model="m", base_url="http://localhost:1/v1", **changes
        ).validate()


# ── the explanation reads Python only ───────────────────────────────────────


def test_an_explanation_never_reads_a_file_that_is_not_python(tmp_path):
    (tmp_path / ".env").write_text("DB_PASSWORD=Hunter2xx\n")
    (tmp_path / "m.py").write_text("x = 1\nraise ValueError\n")
    assert _code_around(tmp_path, {"file": ".env", "line": 1}, remote=True) == ""
    assert "raise ValueError" in _code_around(tmp_path, {"file": "m.py", "line": 2}, remote=True)


# ── the skill's script runs outside the project ─────────────────────────────


def test_check_env_does_not_import_from_the_project(tmp_path):
    marker = tmp_path / "RAN.txt"
    (tmp_path / "ducta.yaml").write_text("version: 2\n")
    (tmp_path / "json.py").write_text(
        f"open({str(marker)!r}, 'w').write('the project ran')\nraise ImportError('planted')\n"
    )
    script = (
        Path(__file__).parents[2]
        / "src"
        / "ducta"
        / "skills"
        / "ducta"
        / "scripts"
        / "check_env.py"
    )
    done = subprocess.run(
        [sys.executable, str(script), "--project", str(tmp_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert done.returncode == 0, done.stderr
    assert not marker.exists()
