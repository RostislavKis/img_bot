#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PROJECT_DUMP.py - Diagnostic script for analyzing the project and workflows.

Generates a full report at docs/PROJECT_DUMP.txt
Used for sharing reports and troubleshooting.

Usage:
    python tools/project_dump.py
"""

import sys
import json
import platform
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Set, Tuple


# Package versions (optional)
try:
    import aiogram
    AIOGRAM_VERSION = aiogram.__version__
except (ImportError, AttributeError):
    AIOGRAM_VERSION = "not installed"

try:
    import httpx
    HTTPX_VERSION = httpx.__version__
except (ImportError, AttributeError):
    HTTPX_VERSION = "not installed"

try:
    import pydantic
    PYDANTIC_VERSION = pydantic.__version__
except (ImportError, AttributeError):
    PYDANTIC_VERSION = "not installed"


PROJECT_ROOT = Path(__file__).parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
WORKFLOWS_DIR = PROJECT_ROOT / "workflows"
OUTPUT_FILE = DOCS_DIR / "PROJECT_DUMP.txt"

# Prompt keys (should match bot/handlers/generate.py)
PROMPT_KEYS = (
    "text",
    "prompt",
    "positive",
    "positive_prompt",
    "prompt_text",
    "text_g",
    "text_l",
    "clip_text",
    "conditioning_text",
)

NEG_KEYS_HINTS = ("negative", "neg", "bad", "undesired")


def is_negative_field(key: str) -> bool:
    k = (key or "").lower()
    return any(x in k for x in NEG_KEYS_HINTS)


def _should_ignore_dir(name: str, ignore_dirs: Set[str]) -> bool:
    """Match exact names + common suffix patterns."""
    if name in ignore_dirs:
        return True
    if name.endswith(".egg-info"):
        return True
    return False


def get_project_tree(root: Path, indent: str = "", ignore_dirs: Set[str] | None = None) -> List[str]:
    """Build project tree using ASCII only."""
    if ignore_dirs is None:
        ignore_dirs = {
            ".venv", "venv", "__pycache__", ".git", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
            "logs", "data", "node_modules", "dist", "build", "htmlcov",
            ".vs", ".idea", ".vscode", ".github",
            "CopilotSnapshots", "CopilotBaseline",
        }

    lines: List[str] = []
    try:
        items = sorted(root.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except PermissionError:
        return [f"{indent}[Permission Denied]"]

    dirs = [p for p in items if p.is_dir() and not _should_ignore_dir(p.name, ignore_dirs)]
    files = [p for p in items if p.is_file() and not p.name.startswith(".")]

    for file in files:
        lines.append(f"{indent}|-- {file.name}")

    for dir_item in dirs:
        lines.append(f"{indent}|-- {dir_item.name}/")
        next_indent = indent + "|   "
        sub_lines = get_project_tree(dir_item, next_indent, ignore_dirs)
        lines.extend(sub_lines[:40])  # limit output per directory

    return lines


def load_workflow(wf_path: Path) -> Tuple[Dict[str, Any], str, str]:
    """
    Load workflow and detect format.

    Returns (normalized_workflow, format_type, error_msg)
    format_type: "nodes_wrapper", "flat", or "error"
    """
    try:
        data = json.loads(wf_path.read_text(encoding="utf-8"))

        if not isinstance(data, dict):
            return {}, "error", f"Workflow not dict, got {type(data).__name__}"

        if "nodes" in data and isinstance(data["nodes"], dict):
            workflow = data["nodes"]
            fmt = "nodes_wrapper"
        else:
            workflow = {k: v for k, v in data.items() if isinstance(v, dict)}
            fmt = "flat"

        if not workflow:
            return {}, "error", "Workflow has no nodes"

        return workflow, fmt, ""

    except json.JSONDecodeError as e:
        return {}, "error", f"JSON error: {str(e)[:100]}"
    except Exception as e:
        return {}, "error", f"Error: {str(e)[:100]}"


def find_prompt_targets(workflow: Dict[str, Any]) -> List[Dict[str, str]]:
    """Find prompt injection targets: {"node_id","class_type","key"}."""
    targets: List[Dict[str, str]] = []

    # Phase 1: known keys
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue

        class_type = str(node.get("class_type") or "unknown")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue

        for prompt_key in PROMPT_KEYS:
            if prompt_key in inputs and isinstance(inputs.get(prompt_key), str):
                if not is_negative_field(prompt_key):
                    targets.append({"node_id": str(node_id), "class_type": class_type, "key": prompt_key})

    # Phase 2: fallback by name contains prompt/text
    if not targets:
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type") or "unknown")
            inputs = node.get("inputs")
            if not isinstance(inputs, dict):
                continue

            for k, v in inputs.items():
                if not isinstance(v, str):
                    continue
                lk = str(k).lower()
                if is_negative_field(lk):
                    continue
                if ("prompt" in lk) or ("text" in lk):
                    targets.append({"node_id": str(node_id), "class_type": class_type, "key": str(k)})

    return sorted(targets, key=lambda t: (t["node_id"], t["key"]))


def analyze_workflow(wf_path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "filename": wf_path.name,
        "errors": [],
        "format": "unknown",
        "nodes_count": 0,
        "class_types": [],
        "string_fields": [],
        "special_keys": {},
        "prompt_targets": [],
        "diagnostic_table": [],
    }

    workflow, fmt, error = load_workflow(wf_path)
    if error:
        result["errors"].append(error)
        result["format"] = "error"
        return result

    result["format"] = fmt
    result["nodes_count"] = len(workflow)

    class_types = {str(node.get("class_type") or "unknown") for node in workflow.values() if isinstance(node, dict)}
    result["class_types"] = sorted(list(class_types))[:20]

    string_fields = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "unknown")
        inputs = node.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for k, v in inputs.items():
            if isinstance(v, str):
                string_fields.append(
                    {"node_id": str(node_id), "class_type": class_type, "key": str(k), "value_preview": str(v)[:50]}
                )
    result["string_fields"] = string_fields

    special_keys_to_find = ["ckpt_name", "unet_name", "width", "height", "steps", "cfg", "guidance", "seed"]
    special: Dict[str, Any] = {}
    for key in special_keys_to_find:
        found = []
        for node_id, node in workflow.items():
            if not isinstance(node, dict):
                continue
            inputs = node.get("inputs")
            if isinstance(inputs, dict) and key in inputs:
                found.append({"node_id": str(node_id), "value": str(inputs[key])[:50]})
        if found:
            special[key] = found
    result["special_keys"] = special

    targets = find_prompt_targets(workflow)
    result["prompt_targets"] = targets

    if not targets:
        table_rows = []
        for node_id, node in sorted(workflow.items(), key=lambda kv: str(kv[0])):
            if not isinstance(node, dict):
                continue
            class_type = str(node.get("class_type") or "unknown")
            inputs = node.get("inputs", {})
            string_keys = [str(k) for k, v in inputs.items() if isinstance(v, str)]
            table_rows.append({"node_id": str(node_id), "class_type": class_type, "string_keys": ", ".join(string_keys) or "(none)"})
        result["diagnostic_table"] = table_rows

    return result


def generate_report(workflows_dir: Path) -> str:
    lines: List[str] = []

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append("=" * 100)
    lines.append(f"PROJECT DUMP - {now}")
    lines.append(f"Python: {sys.version.split()[0]}")
    lines.append(f"OS: {platform.system()} {platform.release()}")
    lines.append(f"Project: {PROJECT_ROOT}")
    lines.append("=" * 100)
    lines.append("")

    lines.append("VERSIONS:")
    lines.append(f"  aiogram: {AIOGRAM_VERSION}")
    lines.append(f"  httpx: {HTTPX_VERSION}")
    lines.append(f"  pydantic: {PYDANTIC_VERSION}")
    lines.append("")

    lines.append("PROJECT TREE:")
    lines.extend(get_project_tree(PROJECT_ROOT)[:200])
    lines.append("")

    lines.append("=" * 100)
    lines.append("WORKFLOW ANALYSIS")
    lines.append("=" * 100)
    lines.append("")

    workflow_errors = 0
    workflow_ok = 0

    if workflows_dir.exists():
        for wf_file in sorted(workflows_dir.glob("*.json"), key=lambda p: p.name.lower()):
            analysis = analyze_workflow(wf_file)

            lines.append(f"FILE: {analysis['filename']}")
            lines.append(f"  Format: {analysis['format']}")

            if analysis["errors"]:
                lines.append(f"  ERRORS: {' | '.join(analysis['errors'])}")
                workflow_errors += 1
                lines.append("")
                continue

            workflow_ok += 1
            lines.append(f"  Nodes: {analysis['nodes_count']}")
            lines.append(f"  Class Types: {', '.join(analysis['class_types'][:10])}")

            if analysis["string_fields"]:
                lines.append(f"  String Fields ({len(analysis['string_fields'])}):")
                for sf in analysis["string_fields"][:5]:
                    lines.append(f"    - node={sf['node_id']} class={sf['class_type']} key={sf['key']}")
                if len(analysis["string_fields"]) > 5:
                    lines.append(f"    ... and {len(analysis['string_fields']) - 5} more")

            if analysis["special_keys"]:
                lines.append("  Special Keys:")
                for key, occurrences in analysis["special_keys"].items():
                    lines.append(f"    - {key}: {len(occurrences)} occurrence(s)")
                    for occ in occurrences[:2]:
                        lines.append(f"        node={occ['node_id']} value={occ['value']}")

            if analysis["prompt_targets"]:
                lines.append(f"  Prompt Injection Targets ({len(analysis['prompt_targets'])}):")
                for target in analysis["prompt_targets"]:
                    lines.append(f"    - node={target['node_id']} class={target['class_type']} key={target['key']}")
            else:
                lines.append("  Prompt Injection Targets: NONE (diagnostic table below)")
                if analysis["diagnostic_table"]:
                    lines.append("    Diagnostic Table:")
                    lines.append(f"    {'Node ID':<10} {'Class Type':<25} {'String Keys':<50}")
                    for row in analysis["diagnostic_table"]:
                        lines.append(f"    {row['node_id']:<10} {row['class_type']:<25} {row['string_keys']:<50}")

            lines.append("")

    lines.append("=" * 100)
    lines.append("SUMMARY")
    lines.append("=" * 100)
    lines.append(f"Workflow files: {workflow_ok} OK, {workflow_errors} ERRORS")
    lines.append(f"Report generated: {now}")
    lines.append(f"Output: {OUTPUT_FILE}")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    report = generate_report(WORKFLOWS_DIR)
    OUTPUT_FILE.write_text(report, encoding="utf-8")

    print("\n" + "=" * 80)
    print("OK: PROJECT_DUMP generated successfully!")
    print(f"Output: {OUTPUT_FILE}")
    print(f"Size: {len(report)} bytes")
    print("=" * 80)

    lines = report.split("\n")
    try:
        idx = next(i for i, line in enumerate(lines) if line.strip() == "SUMMARY")
        for line in lines[idx:idx + 10]:
            print(line)
    except StopIteration:
        pass

    print("=" * 80)


if __name__ == "__main__":
    main()
