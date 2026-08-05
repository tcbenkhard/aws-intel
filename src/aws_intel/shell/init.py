"""Render shell initialization scripts."""


def render_zsh_init() -> str:
    """Return zsh code that labels shells authenticated by awsi."""
    return """if [[ -n ${AWSI_ACCOUNT:-} ]]; then
  if [[ -n ${AWSI_ROLE:-} ]]; then
    _awsi_prompt_prefix="[${AWSI_ROLE}@${AWSI_ACCOUNT}] "
  else
    _awsi_prompt_prefix="[${AWSI_ACCOUNT}] "
  fi
  _awsi_plain_prefix="${_awsi_prompt_prefix}"
  if [[ -n ${AWSI_COLOR:-} ]]; then
    _awsi_prompt_prefix="%F{${AWSI_COLOR}}${_awsi_prompt_prefix}%f"
  fi
  if [[ ${PROMPT:-} != "${_awsi_prompt_prefix}"* && ${PROMPT:-} != "${_awsi_plain_prefix}"* ]]; then
    PROMPT="${_awsi_prompt_prefix}${PROMPT:-%n@%m %1~ %# }"
  fi
  unset _awsi_prompt_prefix _awsi_plain_prefix
fi"""
