"""Render shell initialization scripts."""


def render_zsh_init() -> str:
    """Return zsh code that labels shells authenticated by awsi."""
    return """if [[ -n ${AWSI_ACCOUNT:-} ]]; then
  if [[ -n ${AWSI_ROLE:-} ]]; then
    _awsi_prompt_prefix="[${AWSI_ROLE}@${AWSI_ACCOUNT}] "
  else
    _awsi_prompt_prefix="[${AWSI_ACCOUNT}] "
  fi
  if [[ ${PROMPT:-} != "${_awsi_prompt_prefix}"* ]]; then
    PROMPT="${_awsi_prompt_prefix}${PROMPT:-%n@%m %1~ %# }"
  fi
  unset _awsi_prompt_prefix
fi"""
