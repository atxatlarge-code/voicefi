---
name: next
description: Instantly inspects the workspace living pipeline registry (.agents/ACTIVE_PIPELINES.md) and current conversation context to report the exact pending phase and copy-pasteable resume prompt without scrolling or generating unneeded code.
---

# /next Skill: Instant Thread & Pipeline Catch-Up

This skill activates when the user types `/next`, `/catchup`, or asks "what's next?" / "where were we?".

## Execution Steps:
1. **Check Workspace Pipeline Registry**:
   Read `.agents/ACTIVE_PIPELINES.md` in the current project root.
2. **Reconcile with Active Conversation**:
   Look at recent milestones discussed in the thread.
3. **Output Immediate Handoff Card**:
   Do NOT execute heavy code changes, rewrite existing files, or generate long multi-page plans. Output a concise 4-line status card:

```markdown
### 📍 Current Pipeline: [Pipeline Name]
- **Last Completed**: [1-sentence summary of last finished step]
- **Active Next Step**: [1-sentence description of the next step]
- **Queued Thereafter**: [Brief list of remaining steps, if any]

Ready to execute:
> **Resume Prompt**: `Proceed with [Step Name]`
```
