---
name: audit
description: Audit a V-cloak module against its checklist and the global checks G1-G10. Use when the user types "audit", "/audit Mxx", or at step 6 of every session.
---
Target: `$ARGUMENTS` if it names a module, otherwise `STATE.md → current_module`.

1. Read `ai/LOGGING_AND_AUDIT.md §3` (global checks) and the target module's *Audit checklist*.
2. For each item, run the stated check command. Mark PASS / FAIL / N/A. Every PASS needs an evidence
   path (a runs/ directory, a test output file, or a commit hash). "Looks fine" is not evidence.
3. Append an entry to `state/AUDIT_LOG.md` in the format of `ai/LOGGING_AND_AUDIT.md §4`.
4. If any item FAILS: set the module to `AUDIT_FAILED` in STATE.md, open an ISSUE tagged
   `BLOCKS: <module>`, and describe the fix. Do not mark the module DONE.
5. If everything passes: set the module to `DONE`, run `git tag <Mxx>-done`, and advance `next_unit`.
