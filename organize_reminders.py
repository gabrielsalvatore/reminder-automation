#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════╗
║             Apple Reminders Organizer                        ║
║  Uses Claude AI to automatically sort your reminders         ║
║  into clean, logical lists.                                  ║
╚══════════════════════════════════════════════════════════════╝

SETUP (one time):
  1. Install the Anthropic library:
       pip3 install anthropic

  2. Get a free API key at: https://console.anthropic.com
     Then set it in your terminal:
       export ANTHROPIC_API_KEY="sk-ant-..."
     Or paste it directly into ANTHROPIC_API_KEY below.

  3. Run in preview mode first (DRY_RUN = True below):
       python3 organize_reminders.py

  4. When you're happy with the plan, set DRY_RUN = False
     and run again to apply the changes.

NOTE: This script only touches *incomplete* reminders.
      Completed reminders are never modified.
"""

import subprocess
import json
import os
import sys
import re

# ─────────────────────────────────────────────
#  CONFIGURATION  ← edit these two lines
# ─────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DRY_RUN = True   # True = preview only  |  False = actually reorganize
# ─────────────────────────────────────────────


# ── AppleScript helpers ───────────────────────────────────────

def run_applescript(script: str) -> str:
    """Execute an AppleScript and return its stdout."""
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"\n❌  AppleScript error:\n{result.stderr.strip()}")
        sys.exit(1)
    return result.stdout.strip()


# ── Reading reminders ─────────────────────────────────────────

def get_all_reminders() -> list[dict]:
    """
    Pull every incomplete reminder from every list.
    Returns a list of dicts: {list, name, notes}
    """
    script = '''
    tell application "Reminders"
        set output to ""
        repeat with aList in every list
            set listName to name of aList
            set incompleteReminders to every reminder of aList whose completed is false
            repeat with r in incompleteReminders
                set rName to name of r
                set rBody to body of r
                if rBody is missing value then set rBody to ""
                set output to output & listName & "|||" & rName & "|||" & rBody & "~~ROW~~"
            end repeat
        end repeat
        return output
    end tell
    '''
    raw = run_applescript(script)
    reminders = []
    for row in raw.split("~~ROW~~"):
        row = row.strip()
        if not row:
            continue
        parts = row.split("|||")
        if len(parts) < 2:
            continue
        reminders.append({
            "list":  parts[0].strip(),
            "name":  parts[1].strip(),
            "notes": parts[2].strip() if len(parts) > 2 else "",
        })
    return reminders


# ── Claude AI categorization ──────────────────────────────────

def categorize_with_claude(reminders: list[dict]) -> dict:
    """
    Send all reminders to Claude and get back a reorganization plan.
    Returns: {"lists": [...], "assignments": {"Reminder name": "Target list", ...}}
    """
    try:
        from anthropic import Anthropic
    except ImportError:
        print("\n❌  The 'anthropic' package is not installed.")
        print("    Run:  pip3 install anthropic\n")
        sys.exit(1)

    if not ANTHROPIC_API_KEY:
        print("\n❌  No API key found.")
        print("    Set it with:  export ANTHROPIC_API_KEY='sk-ant-...'")
        print("    Or paste it into ANTHROPIC_API_KEY at the top of this script.\n")
        sys.exit(1)

    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    # Build the reminder list for the prompt
    lines = []
    for r in reminders:
        entry = f"- [currently in: {r['list']}] {r['name']}"
        if r["notes"]:
            entry += f"  →  notes: {r['notes']}"
        lines.append(entry)
    reminder_text = "\n".join(lines)

    prompt = f"""You are helping a person organize their Apple Reminders app.
Here are all their current incomplete reminders (with which list they're currently in):

{reminder_text}

Your job: suggest a clean, logical list structure and assign every reminder to the best list.

Return ONLY valid JSON — no markdown, no explanation — in exactly this format:
{{
  "lists": ["List A", "List B", "List C"],
  "assignments": {{
    "Exact reminder name as written above": "Target List Name",
    ...
  }}
}}

Rules:
- Propose 3–7 focused lists (e.g., Work, Shopping, Health, Home, Personal, Finance, Travel)
- Assign EVERY reminder to exactly one list
- Use the reminder's name exactly as written (copy-paste it)
- Keep or reuse existing list names when they're already sensible
- Don't create a list with only 1 item — fold it into a broader category
- Prefer natural, short list names a person would use on their phone"""

    print("  Sending to Claude... ", end="", flush=True)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    print("done.")

    raw = response.content[0].text.strip()

    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"\n❌  Could not parse Claude's response as JSON: {e}")
        print("Raw response:\n", raw)
        sys.exit(1)


# ── Applying changes via AppleScript ─────────────────────────

def get_existing_lists() -> set[str]:
    script = 'tell application "Reminders" to return name of every list'
    raw = run_applescript(script)
    # AppleScript returns a comma-separated string like: Reminders, Work, Shopping
    return {name.strip() for name in raw.split(",")}


def create_list(list_name: str):
    safe = list_name.replace('"', '\\"')
    run_applescript(f'tell application "Reminders" to make new list with properties {{name:"{safe}"}}')


def move_reminder(reminder_name: str, source_list: str, target_list: str):
    safe_name   = reminder_name.replace('"', '\\"').replace("'", "\\'")
    safe_source = source_list.replace('"', '\\"')
    safe_target = target_list.replace('"', '\\"')
    script = f'''
    tell application "Reminders"
        set srcList to list "{safe_source}"
        set dstList to list "{safe_target}"
        set matches to (every reminder of srcList whose name is "{safe_name}" and completed is false)
        if length of matches > 0 then
            move item 1 of matches to dstList
        end if
    end tell
    '''
    run_applescript(script)


# ── Main ──────────────────────────────────────────────────────

def print_banner():
    print()
    print("=" * 58)
    print("  🗂   Apple Reminders Organizer")
    if DRY_RUN:
        print("       MODE: Preview (no changes will be made)")
    else:
        print("       MODE: Live (reminders WILL be moved)")
    print("=" * 58)
    print()


def main():
    print_banner()

    # 1. Read all reminders
    print("📋  Reading your reminders from the Reminders app...")
    reminders = get_all_reminders()

    if not reminders:
        print("\n✅  No incomplete reminders found — nothing to organize!")
        return

    current_lists = sorted(set(r["list"] for r in reminders))
    print(f"    Found {len(reminders)} incomplete reminders across {len(current_lists)} list(s):")
    for lst in current_lists:
        count = sum(1 for r in reminders if r["list"] == lst)
        print(f"      • {lst}  ({count} items)")
    print()

    # 2. Ask Claude for a plan
    print("🤖  Asking Claude AI to suggest an organization plan...")
    plan = categorize_with_claude(reminders)
    print()

    # 3. Print the proposed plan
    by_target: dict[str, list] = {}
    for rname, tlist in plan["assignments"].items():
        by_target.setdefault(tlist, []).append(rname)

    # Check for any reminders that Claude missed
    assigned_names = set(plan["assignments"].keys())
    reminder_names = {r["name"] for r in reminders}
    unassigned = reminder_names - assigned_names
    if unassigned:
        by_target.setdefault("⚠️  Unassigned", list(unassigned))

    print("─" * 58)
    print("  PROPOSED LAYOUT")
    print("─" * 58)

    moves_needed = 0
    for tlist in sorted(by_target.keys()):
        items = sorted(by_target[tlist])
        print(f"\n  📁  {tlist}  ({len(items)} items)")
        for item in items:
            current = next((r["list"] for r in reminders if r["name"] == item), "?")
            if current == tlist:
                print(f"       ✓ {item}")
            else:
                print(f"       → {item}   (from: {current})")
                moves_needed += 1

    print()
    print("─" * 58)
    new_lists = [l for l in plan["lists"] if l not in get_existing_lists()]
    print(f"  New lists to create : {len(new_lists)}")
    print(f"  Reminders to move   : {moves_needed}")
    print("─" * 58)
    print()

    # 4. Dry-run or apply
    if DRY_RUN:
        print("👀  DRY RUN — nothing was changed.")
        print()
        print("  To apply this plan:")
        print("    1. Open organize_reminders.py")
        print("    2. Change  DRY_RUN = True  →  DRY_RUN = False")
        print("    3. Run the script again")
        print()
        return

    # ── Apply changes ──
    print("⚙️   Applying changes...")
    existing = get_existing_lists()

    # Create missing lists first
    for lst in plan["lists"]:
        if lst not in existing:
            print(f"  + Creating list '{lst}'")
            create_list(lst)

    # Move reminders
    moved = 0
    errors = 0
    for reminder in reminders:
        target = plan["assignments"].get(reminder["name"])
        if not target or target == reminder["list"]:
            continue
        try:
            print(f"  ↳  Moving '{reminder['name']}' → {target}")
            move_reminder(reminder["name"], reminder["list"], target)
            moved += 1
        except SystemExit:
            print(f"     ⚠️  Could not move '{reminder['name']}' — skipping")
            errors += 1

    print()
    print("=" * 58)
    print(f"  ✅  Done!  Moved {moved} reminder(s).", end="")
    if errors:
        print(f"  ({errors} skipped due to errors)", end="")
    print()
    print("=" * 58)
    print()


if __name__ == "__main__":
    main()
