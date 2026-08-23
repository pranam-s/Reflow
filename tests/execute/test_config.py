"""Tests for reflow.execute.config."""

import pytest

from reflow.execute.config import KEY_ID_ENV_VAR, KEY_SECRET_ENV_VAR, load_credentials
from reflow.execute.errors import MissingCredentialsError


def test_load_credentials_reads_both_values() -> None:
    env = {KEY_ID_ENV_VAR: "rzp_test_abc", KEY_SECRET_ENV_VAR: "shh"}
    assert load_credentials(env) == ("rzp_test_abc", "shh")


def test_load_credentials_raises_when_key_id_missing() -> None:
    with pytest.raises(MissingCredentialsError):
        load_credentials({KEY_SECRET_ENV_VAR: "shh"})


def test_load_credentials_raises_when_key_secret_missing() -> None:
    with pytest.raises(MissingCredentialsError):
        load_credentials({KEY_ID_ENV_VAR: "rzp_test_abc"})


def test_load_credentials_raises_when_both_empty() -> None:
    with pytest.raises(MissingCredentialsError):
        load_credentials({KEY_ID_ENV_VAR: "", KEY_SECRET_ENV_VAR: ""})
