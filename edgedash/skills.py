import argparse
import re
import string
import sys
from collections import Counter
from typing import Any

from edgedash import llm, storage
from edgedash.config import Config, load_config

ALIAS_SUGGESTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "canonical": {"type": "string"},
                    "variants": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "confidence": {
                        "type": "string",
                        "enum": ["high", "low"],
                    },
                },
                "required": ["canonical", "variants", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["proposals"],
    "additionalProperties": False,
}


def canonical(raw: str, aliases: dict[str, str] | None = None) -> str:
    if not isinstance(raw, str) or not raw.strip():
        return ""

    if aliases is None:
        aliases = {}

    # 1. Lowercase
    s = raw.lower()

    # 2. Drop parenthetical qualifiers: "kubernetes (eks)" -> "kubernetes"
    s = re.sub(r"[\(\[\{].*?[\)\]\}]", "", s)

    # 3. Collapse internal whitespace
    s = re.sub(r"\s+", " ", s).strip()

    # 4. Strip surrounding whitespace and surrounding punctuation (preserving +, #, ., -, / inside/end of skills like c++, c#, .net)
    s = re.sub(r"^[^a-zA-Z0-9+#.-]+|[^a-zA-Z0-9+#.-]+$", "", s).strip()

    # 5. Apply alias map
    return aliases.get(s, s)


def audit_skills(config: Config) -> None:
    db_path = config.db_path
    aliases = getattr(config, "skill_aliases", {})

    extractions = storage.get_all_extractions(db_path)
    if not extractions:
        print("No extracted skills found in database.")
        return

    raw_counter: Counter[str] = Counter()
    for ext in extractions:
        skills_list = ext.get("required_skills", [])
        if isinstance(skills_list, list):
            for item in skills_list:
                if isinstance(item, str) and item.strip():
                    raw_counter[item.strip()] += 1

    total_unique = len(raw_counter)
    total_occurrences = sum(raw_counter.values())

    print("\n" + "=" * 80)
    print(" SKILL CANONICALISATION AUDIT REPORT".center(80))
    print("=" * 80)
    print(f"  * Total Extractions    : {len(extractions)}")
    print(f"  * Total Skill Instances: {total_occurrences}")
    print(f"  * Unique Raw Skills    : {total_unique}")

    # Top 40 most common raw skill strings
    most_common = raw_counter.most_common(40)
    print("\n" + "-" * 80)
    print(f" TOP {len(most_common)} MOST COMMON RAW SKILLS & CANONICAL MAPPINGS")
    print("-" * 80)
    print(f" {'RAW SKILL':<35} | {'COUNT':<6} | {'CANONICAL FORM'}")
    print("-" * 80)
    for raw_skill, count in most_common:
        canon = canonical(raw_skill, aliases)
        alias_note = f"-> {canon}" if canon != raw_skill.lower().strip() else canon
        print(f" {raw_skill[:35]:<35} | {count:<6} | {alias_note}")

    # Raw strings seen ONLY ONCE (typos, junk, or long sentences)
    singletons = [skill for skill, count in raw_counter.items() if count == 1]
    print("\n" + "-" * 80)
    print(f" RAW SKILLS SEEN ONLY ONCE ({len(singletons)} items — potential typos/junk/full sentences)")
    print("-" * 80)
    for idx, skill in enumerate(sorted(singletons), 1):
        canon = canonical(skill, aliases)
        print(f"  {idx:3d}. '{skill}' -> '{canon}'")

    print("\n" + "=" * 80 + "\n")


def suggest_aliases(config: Config) -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    existing_aliases = getattr(config, "skill_aliases", {})
    extractions = storage.get_all_extractions(config.db_path)

    if not extractions:
        print("No extracted skills found in database.")
        return

    # Count canonical skills
    raw_counter: Counter[str] = Counter()
    for ext in extractions:
        skills_list = ext.get("required_skills", [])
        if isinstance(skills_list, list):
            for item in skills_list:
                if isinstance(item, str) and item.strip():
                    canon = canonical(item.strip(), existing_aliases)
                    if canon:
                        raw_counter[canon] += 1

    # Filter out skills already in alias map keys
    unmapped_skills = {
        skill: count
        for skill, count in raw_counter.items()
        if skill not in existing_aliases
    }

    if not unmapped_skills:
        print("\nAll extracted skills are already mapped in skill_aliases map in config.yaml!\n")
        return

    # Prepare single LLM prompt
    skills_list_formatted = "\n".join(
        f"- {skill} (count: {count})"
        for skill, count in sorted(unmapped_skills.items(), key=lambda x: x[1], reverse=True)
    )

    prompt = f"""You are an expert technical recruiter and developer skills ontology engine.
Below is a list of canonical skill strings extracted from job descriptions, along with occurrence counts:

{skills_list_formatted}

Task: Propose groupings of strings that refer to the EXACT SAME underlying skill or language (such as synonyms, language translations like 'deutsch' -> 'german', or minor spelling variants).

CRITICAL CONSTRAINTS:
1. Group ONLY terms that strictly refer to the EXACT SAME skill or language.
2. DO NOT group distinct technologies, tools, or languages (e.g. DO NOT group Node.js and JavaScript; DO NOT group Docker and Kubernetes; DO NOT group Python and Pandas).
3. If a term is a distinct standalone skill, do NOT propose an alias for it.
4. Set confidence to "high" for unambiguous matches and "low" for ambiguous matches.
"""

    res = llm.complete_json(prompt=prompt, schema=ALIAS_SUGGESTION_SCHEMA, config=config)
    proposals = res.get("proposals", []) if isinstance(res, dict) else []

    # Header and Warning (Requirement 4)
    print("\n" + "=" * 90)
    print(" ⚠️  WARNING: ALIAS SUGGESTIONS REQUIRE HUMAN REVIEW (Rule 23)".center(90))
    print("=" * 90)
    print("  * These are suggestions generated by LLM analysis.")
    print("  * Rule 23: Merging distinct skills is worse than leaving them separate.")
    print("  * NO files have been modified. Review each proposed alias before pasting into config.yaml.")
    print("=" * 90 + "\n")

    if not proposals:
        print("No alias groupings proposed by model.\n")
        return

    print("# PROPOSED ALIAS MAP ADDITIONS (Ready-to-paste into config.yaml):\n")
    print("skill_aliases:")

    # Conflict detection (Requirement 5)
    for prop in proposals:
        target_canon = str(prop.get("canonical", "")).strip().lower()
        variants = [str(v).strip().lower() for v in prop.get("variants", []) if str(v).strip()]
        confidence = str(prop.get("confidence", "low")).upper()

        if not target_canon or not variants:
            continue

        conflicts: list[str] = []

        # Check existing explicit alias keys
        for v in variants:
            if v in existing_aliases:
                existing_target = existing_aliases[v]
                if existing_target != target_canon:
                    conflicts.append(
                        f"Variant '{v}' is already explicitly mapped to '{existing_target}' in config.yaml"
                    )
                else:
                    conflicts.append(
                        f"Variant '{v}' already has an explicit alias entry in config.yaml ('{v}: {existing_target}')"
                    )

        # Check if proposal groups terms that map to different targets in existing_aliases
        existing_targets_in_group = {
            existing_aliases[v] for v in variants if v in existing_aliases
        }
        if len(existing_targets_in_group) > 1:
            conflicts.append(
                f"Proposal groups terms mapped to different existing targets in config.yaml: {sorted(existing_targets_in_group)}"
            )

        if conflicts:
            print(f"\n  # 🚨 CONFLICT DETECTED with existing config.yaml choice:")
            for c in conflicts:
                print(f"  #    - {c}")
            print(f"  # Proposed grouping was: {variants} -> '{target_canon}' [{confidence}]")
        else:
            print(f"\n  # [{confidence} CONFIDENCE] Grouping for '{target_canon}'")
            for v in variants:
                if v != target_canon:
                    print(f"  {v}: \"{target_canon}\"")

    print("\n" + "=" * 90 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Skill canonicalisation tools and audit")
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Audit extracted required_skills in database and show canonical mappings.",
    )
    parser.add_argument(
        "--suggest-aliases",
        action="store_true",
        help="Use LLM to propose alias groupings for unmapped skill strings (read-only).",
    )
    args = parser.parse_args()

    cfg = load_config()

    if args.audit:
        audit_skills(cfg)
    elif args.suggest_aliases:
        suggest_aliases(cfg)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

