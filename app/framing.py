"""Banned framing words (build spec section 1): the one list used by the memo check and by
the repo test. This file is the only place they may appear."""
BANNED_FRAMING = ["clinical decision support", "patient recommendation", "treatment guidance",
                  "treatment recommendation", "diagnose", "diagnosis", "prescribe",
                  "patient safety advisor", "chat with your pdf", "ask the protocol",
                  "ai predicts whether your trial will fail", "oracle"]

# Blame words the mismatch check must never show: a difference between two public documents is a
# prompt to check, not a finding of fault. (The agent prompt and docs/mismatch.md quote this ban.)
BANNED_BLAME = ["non-compliance", "noncompliance", "non-compliant", "noncompliant", "violation", "misconduct",
                "fraud", "medical advice to"]
