# REVIEW FEEDBACK — panel comments and how each was addressed
#
# Review 4 criterion 1 (2 marks) is awarded for *evidence* that Review-3 and draft-report
# observations were addressed. That evidence is this file.
#
# HUMAN: right after each review, paste every comment the panel made — verbatim, even the vague ones.
# AGENT: never invent a comment. If this file has no Review-3 entries and the human is planning
# Review-4 work, ask them for the panel's comments before continuing.
#
# Status: OPEN -> IN_PROGRESS -> ADDRESSED (needs a commit hash and, where relevant, a run dir)

## Review 2 — <date>
### RF-1 [ADDRESSED 7b20d4f] "How will you secure the session?"
Raised by: panel
Action: specified and implemented DPoP-bound tokens, refresh-family rotation, one-time WebSocket
tickets, Argon2id login, log redaction; verified by the 12-scenario E5 attack matrix.
Evidence: M11 · runs/<...>_M11_e5 · results/session/e5_matrix.json · paper Sec. V

## Review 3 — <date>
### RF-2 [OPEN] <paste the panel's comment here, verbatim>
Raised by: <panel member / guide>
Action: <what you will change — filled in by the agent when the work is planned>
Evidence: <commit, run dir, file>

### RF-3 [OPEN] <...>

## Draft report review — <date>
### RF-4 [OPEN] <...>

---
## Summary (regenerate before Review 4)
| ID | Source | Status | Evidence |
|---|---|---|---|
| RF-1 | Review 2 | ADDRESSED | 7b20d4f |
