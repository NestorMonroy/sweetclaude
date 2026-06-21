#!/usr/bin/env python3
"""
Deterministic context budget check for SweetClaude.

Reads installed skills from the plugin cache.
Sums character length of `description:` for skills WITHOUT
`disable-model-invocation: true`. Compares to the configured budget.

Exit 0 = under budget. Exit 1 = over budget.
"""
import glob
import json
import os
import re
import sys

_script_dir = os.path.dirname(os.path.abspath(__file__))
INSTALLED = os.path.join(os.path.dirname(_script_dir), 'skills', '*', 'SKILL.md')
SETTINGS = os.path.expanduser('~/.claude/settings.json')

CONTEXT_TOKENS = 200_000  # default Claude Code context
CHARS_PER_TOKEN = 4       # rough heuristic — same one Claude Code uses internally


def main() -> int:
    fraction = 0.01
    if os.path.exists(SETTINGS):
        with open(SETTINGS) as f:
            cfg = json.load(f)
        fraction = cfg.get('skillListingBudgetFraction', 0.01)

    budget_chars = int(CONTEXT_TOKENS * fraction * CHARS_PER_TOKEN)

    ambient_chars = 0
    ambient_skills = []
    disabled_count = 0

    for f in sorted(glob.glob(INSTALLED)):
        content = open(f).read()
        if re.search(r'^disable-model-invocation:\s*true\s*$',
                     content, re.MULTILINE):
            disabled_count += 1
            continue
        m = re.search(r'^description:\s*["\']?(.*?)["\']?\s*$',
                      content, re.MULTILINE)
        desc = m.group(1).strip() if m else ''
        ambient_chars += len(desc)
        ambient_skills.append((len(desc), os.path.basename(os.path.dirname(f))))

    headroom = budget_chars - ambient_chars

    print(f"Budget fraction:           {fraction}")
    print(f"Computed budget:           {budget_chars} chars")
    print(f"Skills with disable flag:  {disabled_count}")
    print(f"Ambient skills:            {len(ambient_skills)}")
    print(f"Ambient char usage:        {ambient_chars} chars")
    print(f"Headroom:                  {headroom} chars")
    print()
    print("Top 10 ambient skills by description length:")
    for chars, name in sorted(ambient_skills, reverse=True)[:10]:
        print(f"  {chars:5d}  {name}")

    if headroom < 0:
        print()
        print(f"FAIL: over budget by {-headroom} chars")
        return 1
    print()
    print("PASS: within budget")
    return 0


if __name__ == '__main__':
    sys.exit(main())
