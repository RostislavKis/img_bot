# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
WF_DIR = ROOT / "workflows"
OUT = ROOT / "docs" / "WORKFLOWS_REFERENCE.md"


def _normalize_nodes(workflow: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Приводит nodes к формату dict[str, dict].
    Встречаются варианты:
      - {"nodes": {...}}  (Comfy workflow export)
      - {"nodes": [ {...}, {...} ]} (другой формат)
      - workflow как dict { "0": {...}, "1": {...} } (редко)
    """
    nodes = None

    if isinstance(workflow, dict):
        nodes = workflow.get("nodes", None)

        # Иногда nodes вообще отсутствует, а корень — это уже mapping нод
        if nodes is None:
            # эвристика: если в корне много ключей-чисел и значений-объектов
            if all(isinstance(k, str) and k.isdigit() for k in workflow.keys()) and any(isinstance(v, dict) for v in workflow.values()):
                return {str(k): (v if isinstance(v, dict) else {"_value": v}) for k, v in workflow.items()}

    # nodes в виде dict
    if isinstance(nodes, dict):
        return {str(k): (v if isinstance(v, dict) else {"_value": v}) for k, v in nodes.items()}

    # nodes в виде list
    if isinstance(nodes, list):
        out: Dict[str, Dict[str, Any]] = {}
        for i, item in enumerate(nodes):
            if isinstance(item, dict):
                nid = item.get("id", None)
                if nid is None:
                    nid = item.get("node_id", None)
                key = str(nid) if nid is not None else str(i)
                out[key] = item
            else:
                out[str(i)] = {"_value": item}
        return out

    # fallback
    return {}


def _guess_kind(nodes: Dict[str, Dict[str, Any]]) -> str:
    text = json.dumps(nodes, ensure_ascii=False).lower()

    # видео
    if "vhs_videocombine" in text:
        return "video"
    if ("video" in text) and ("mp4" in text or "webm" in text or "frames" in text):
        return "video"

    # изображение
    if "saveimage" in text or '"images"' in text or "vae" in text:
        return "image"

    return "unknown"


def _find_prompt_inputs(nodes: Dict[str, Dict[str, Any]]) -> List[str]:
    hits = set()
    for node in (nodes or {}).values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for k in inputs.keys():
            lk = str(k).lower()
            if lk in ("text", "prompt", "positive", "pos_prompt"):
                hits.add(str(k))
    return sorted(hits) if hits else []


def _has_load_image(nodes: Dict[str, Dict[str, Any]]) -> bool:
    for node in (nodes or {}).values():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", "")).lower()
        if ct in ("loadimage", "load_image"):
            return True
    return False


def _has_mask(nodes: Dict[str, Dict[str, Any]]) -> bool:
    # эвристика: наличие слова mask в inputs/тексте
    text = json.dumps(nodes, ensure_ascii=False).lower()
    return "mask" in text


def _collect_outputs(nodes: Dict[str, Dict[str, Any]]) -> List[str]:
    outs: List[str] = []
    for nid, node in (nodes or {}).items():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type", ""))
        lct = ct.lower()

        if lct in ("saveimage", "save_image"):
            outs.append(f"{nid}: {ct} -> images[]")
        elif "videocombine" in lct:
            outs.append(f"{nid}: {ct} -> video")
        elif ("video" in lct) and ("save" in lct or "combine" in lct):
            outs.append(f"{nid}: {ct} -> video")
        elif ("save" in lct) and ("gif" in lct or "anim" in lct):
            outs.append(f"{nid}: {ct} -> animation")

    return outs


def main() -> int:
    if not WF_DIR.exists():
        raise SystemExit(f"Workflows dir not found: {WF_DIR}")

    files = sorted(WF_DIR.glob("*.json"), key=lambda p: p.name.lower())

    rows: List[Tuple[str, str, bool, bool, List[str], List[str]]] = []

    for p in files:
        wf = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(wf, dict):
            wf = {"nodes": wf}  # fallback на случай если корень список

        nodes = _normalize_nodes(wf)

        kind = _guess_kind(nodes)
        has_load = _has_load_image(nodes)
        has_mask = _has_mask(nodes)
        prompts = _find_prompt_inputs(nodes)
        outs = _collect_outputs(nodes)

        rows.append((p.stem, kind, has_load, has_mask, prompts, outs))

    lines: List[str] = []
    lines.append("# 📚 Справочник по Workflows (img_bot)")
    lines.append("")
    lines.append(f"_Автосгенерировано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_")
    lines.append("")
    lines.append("Этот файл генерируется скриптом `tools/gen_workflows_reference.py` на основе JSON из папки `workflows/`.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📋 Сводная таблица")
    lines.append("")
    lines.append("| Workflow | Тип | LoadImage | Mask | Prompt-поля | Выходы (по нодам) |")
    lines.append("|---|---:|:---:|:---:|---|---|")

    for name, kind, has_load, has_mask, prompts, outs in rows:
        lines.append(
            f"| `{name}` | {kind} | {'✅' if has_load else '—'} | {'✅' if has_mask else '—'} | "
            f"{', '.join(prompts) if prompts else '—'} | {'; '.join(outs) if outs else '—'} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📄 Подробности по каждому workflow")
    lines.append("")

    for name, kind, has_load, has_mask, prompts, outs in rows:
        lines.append(f"### `{name}.json`")
        lines.append("")
        lines.append(f"- **Тип:** `{kind}`")
        lines.append(f"- **LoadImage:** {'да' if has_load else 'нет'}")
        lines.append(f"- **Mask:** {'да' if has_mask else 'нет'}")
        lines.append(f"- **Prompt-поля:** {', '.join(prompts) if prompts else 'не найдено автоматически'}")
        lines.append(f"- **Выходы (эвристика по нодам):**")
        if outs:
            for o in outs:
                lines.append(f"  - {o}")
        else:
            lines.append("  - не найдено автоматически (проверь ноды сохранения)")
        lines.append("")
        lines.append("**Заметки:** дополни вручную (VRAM, время, точные входы), если потребуется.")
        lines.append("")
        lines.append("---")
        lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"OK: wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
