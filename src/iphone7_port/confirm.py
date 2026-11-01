"""Require separate, explicit attestations before any device-changing stage."""

import sys
import time

from .core import PortError, Project, require
from .console import paint, say


CHECKS = [
    ("model", "Confirm the phone is an iPhone 7 GLOBAL (iPhone9,1 / D10AP).", "iPhone9,1"),
    ("version", "Confirm it has just been fully restored to iOS 15.8.8 (19H422).", "15.8.8"),
    ("activation", "Confirm stock iOS is activated and its initial setup is completed.", "ACTIVATED"),
    ("passcode", "Confirm no device passcode is configured.", "NO PASSCODE"),
    ("data", "Confirm there are no important files and no old backup was restored.", "NO IMPORTANT DATA"),
    ("restore", "Confirm you can restore the phone with a computer if installation fails.", "RESTORE READY"),
    ("limitations", "Confirm you accept every experimental limitation printed above.", "I ACCEPT"),
]


def confirm_preconditions(project: Project, ask=input):
    require(sys.stdin.isatty() or ask is not input, "Interactive confirmation requires a terminal. There is no --yes option.")
    say("\nExperimental installation prerequisites\n", 'title')
    for item in project.profile["known_limitations"]:
        say(f"  - {item}", 'warning')
    answers = {}
    for key, question, expected in CHECKS:
        say(f"\n{question}", 'warning')
        answer = ask(paint(f"Type exactly '{expected}' to continue: ", 'warning')).strip()
        if answer != expected:
            raise PortError(f"Confirmation '{key}' was not accepted. No device action was started.")
        answers[key] = True
    project.record("confirmation", {"accepted": answers, "unix_time": time.time()})
    say("\nAll individual confirmations were accepted for this local project.", 'success')


def require_confirmed(project: Project):
    stage = project.stage("confirmation")
    require(all(stage.get("accepted", {}).get(key) is True for key, _, _ in CHECKS), "Individual confirmations are incomplete.")
    require(0 <= time.time() - stage["unix_time"] <= 24 * 3600, "Confirmations expired. Run 'confirm' again.")


def confirm_action(message: str, token: str, ask=input):
    require(sys.stdin.isatty() or ask is not input, "This action requires an interactive terminal.")
    say(f"\n{message}", 'warning')
    require(ask(paint(f"Type '{token}' to proceed: ", 'warning')).strip() == token, "Action cancelled.")
