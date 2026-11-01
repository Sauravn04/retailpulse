# AI usage — fill in as we build

> Amber asks: which AI tools did you use, and one thing the AI got wrong
> that you fixed by checking the source data.
> **Exact tools: TO-CONFIRM by Saurav.** Do not submit this file as fact
> until that line is filled in truthfully.

## Tools used
- TO-CONFIRM: e.g. ChatGPT / Claude / Claude Code / Cursor / Gemini / Copilot
- Used for: scaffolding, debugging, SQL drafting, README drafting.
- Never used for: inventing numbers, or as a substitute for running
  the validation script.

## What AI got wrong (to be filled with real examples from this build)
1. TO BE RECORDED when it happens — with the wrong output, the check
   that caught it, and the fix.
   Known examples from the old project (verify again here, do not copy blindly):
   - pandas index alignment silently giving NaN MAPE — fixed with numpy arrays.
   - Mixing payments total with qty × price revenue.
   - Claiming RandomForest was best when rolling-mean-7 was better on the same holdout.
