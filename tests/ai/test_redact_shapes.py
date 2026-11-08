"""``redact`` (error text) and ``redact_code`` (code) know the same shaped keys.

``redact`` cleans a failed run's error before it reaches the model. It knew URL passwords
and ``password=…`` settings but not the keys whose prefix gives them away, which only
``redact_code`` caught — and neither knew Databricks' ``dapi…`` tokens.
"""

import pytest

from ducta.ai.context import find_secrets, redact, redact_code

# (text, the secret part that must not survive)
ERROR_TEXT = [
    ("jdbc:postgresql://db:5432/x?user=a&password=Hunter2pass", "Hunter2pass"),
    ("jdbc:sqlserver://h:1433;databaseName=d;user=sa;password=Sup3r$ecret;", "Sup3r$ecret"),
    ("postgresql://admin:S3cretPw@host/db", "S3cretPw"),
    ("InvalidAccessKeyId: AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE"),
    ('aws_secret_access_key = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"', "wJalrXUtnFEMI"),
    ("401 for ghp_1234567890abcdefghijklmnopqrstuvwxyz12", "ghp_1234567890"),
    ("key sk-proj-abcdefghijklmnopqrstuvwxyz0123456789ABCD rejected", "sk-proj-abcdef"),
    ("key sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789 rejected", "sk-ant-api03-abc"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF123", "eyJzdWIi"),
    ('connect(host="h", password="pl41nT3xt!")', "pl41nT3xt"),
    ("spark.hadoop.fs.s3a.secret.key: wJalrXUtnFEMIK7MDENGbPxRfiCYEXAMPLE", "wJalrXUtnFEMI"),
    ("https://acct.blob.core.windows.net/c?sv=2022&sig=abcdEFGH1234%2Bxyz%3D", "abcdEFGH1234"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----", "MIIEow"),
    ("slack said no to xoxb-1234567890-1234567890-abcdefghijABCDEFGHIJ", "xoxb-123"),
    ("Invalid token dapi0123456789abcdef0123456789abcdef", "dapi0123"),
    ("Invalid token dapi0123456789abcdef0123456789abcdef-2", "dapi0123"),
]


@pytest.mark.parametrize("text,secret", ERROR_TEXT)
def test_redact_masks_every_known_shape(text, secret):
    assert secret not in redact(text)


# Code: the value is a string literal (``password=os.environ[...]`` is code, not a secret).
CODE = [
    'TOKEN = "dapi0123456789abcdef0123456789abcdef"',
    'client = OpenAI(api_key="sk-proj-abcdefghijklmnopqrstuvwxyz0123456789ABCD")',
    'KEY = """-----BEGIN PRIVATE KEY-----\nMIIEow\n-----END PRIVATE KEY-----"""',
    'url = "jdbc:sqlserver://h;user=sa;password=Sup3r$ecret"',
    'headers = {"Authorization": "Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcDEF123"}',
]


@pytest.mark.parametrize("text", CODE)
def test_redact_code_masks_keys_in_code(text):
    assert find_secrets(text)
    masked = redact_code(text)
    for fragment in ("dapi0123", "sk-proj-abc", "MIIEow", "Sup3r$ecret", "eyJzdWIi"):
        assert fragment not in masked


@pytest.mark.parametrize(
    "text",
    [
        "tokens = tokenize(text)",
        "the role was assigned to the design team",
        "dapi is a word, dapi123 is too short",
        "skeleton sk-short",
    ],
)
def test_ordinary_text_is_left_alone(text):
    assert redact(text) == text
