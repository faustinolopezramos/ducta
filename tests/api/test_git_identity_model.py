"""PUT /api/git/config writes user.name and user.email into .git/config.

A line break in either could add a section of its own (``[core] hooksPath = …``
runs a program on the next commit). GitPython refuses CR/LF/NUL; the request
model refuses every control character, whatever GitPython does.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ducta.api.models.git import GitIdentityConfig


@pytest.mark.parametrize(
    "name",
    ["eve\n[core]\n\thooksPath = /tmp/x", "eve\r", "eve\x00", "eve\tx", "eve\x7f"],
)
def test_a_name_with_control_characters_is_refused(name):
    with pytest.raises(ValidationError, match="single line"):
        GitIdentityConfig(name=name, email="e@example.com")


def test_an_email_with_a_line_break_is_refused():
    with pytest.raises(ValidationError, match="single line"):
        GitIdentityConfig(name="Eve", email="e@example.com\n[core]")


def test_an_ordinary_identity_is_kept():
    identity = GitIdentityConfig(name="  Eve Núñez  ", email="eve@example.com")
    assert (identity.name, identity.email) == ("Eve Núñez", "eve@example.com")
