"""Runbook post-processing: turn free-text steps into actionable ones by
mapping each step to an automated action the dashboard can execute
(sandboxed restart / rollback / isolate)."""
ACTION_KEYWORDS = {
    "rollback": ("rollback", "roll back", "revert", "previous version", "undo"),
    "restart": ("restart", "reboot", "bounce"),
    "isolate": ("isolate", "stop", "quarantine", "drain"),
}


def automate_step(step_text: str):
    lowered = step_text.lower()
    for action, keywords in ACTION_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            return action
    return None


def build_runbook(steps: list) -> list:
    """[{step, action}] — action is one of restart|rollback|isolate or None."""
    return [{"step": text, "action": automate_step(text)} for text in steps]
