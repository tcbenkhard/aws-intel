"""Tests for generated shell initialization scripts."""

from aws_intel.shell.init import render_zsh_init


def test_zsh_init_labels_only_authenticated_shells() -> None:
    script = render_zsh_init()

    assert "AWSI_ACCOUNT" in script
    assert "AWSI_ROLE" in script
    assert '"[${AWSI_ROLE}@${AWSI_ACCOUNT}] "' in script
    assert 'PROMPT="${_awsi_prompt_prefix}${PROMPT' in script
    assert "unset _awsi_prompt_prefix" in script
