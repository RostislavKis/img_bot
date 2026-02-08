# -*- coding: utf-8 -*-
"""
Генератор WORKFLOWS_REFERENCE.md из JSON файлов.
Детерминированный вывод (без timestamp) для стабильных коммитов.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
WF_DIR = ROOT / "workflows"
OUT = ROOT / "docs" / "WORKFLOWS_REFERENCE.md"

VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def _load_workflow_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _normalize_nodes(nodes: Any) -> Dict[str, Dict[str, Any]]:
    """
    ComfyUI workflow JSON может хранить nodes как dict (node_id->node)
    или как list (где node.get('id') является идентификатором).
    Приводим к dict[str, dict].
    """
    if isinstance(nodes, dict):
        out: Dict[str, Dict[str, Any]] = {}
        for k, v in nodes.items():
            if isinstance(v, dict):
                out[str(k)] = v
        return out

    if isinstance(nodes, list):
        out = {}
        for node in nodes:
            if not isinstance(node, dict):
                continue
            nid = node.get("id")
            if nid is None:
                continue
            out[str(nid)] = node
        return out

    return {}


def _guess_kind(nodes: Dict[str, Dict[str, Any]]) -> str:
    """Эвристика определения типа по class_type и содержимому JSON."""
    if not nodes:
        return "unknown"

    # Быстрый путь: по class_type
    has_save_image = False
    has_video = False

    for node in nodes.values():
        ct = str(node.get("class_type", "")).lower()
        if ct in ("saveimage", "save_image"):
            has_save_image = True
        if "videocombine" in ct or ("video" in ct and ("combine" in ct or "save" in ct)):
            has_video = True
        if "vhs_videocombine" in ct:
            has_video = True

    if has_video:
        return "video"
    if has_save_image:
        return "image"

    # Медленный путь: полный текст
    text = json.dumps(nodes, ensure_ascii=False).lower()
    if "vhs_videocombine" in text:
        return "video"
    if "saveimage" in text or '"images"' in text:
        return "image"
    return "unknown"


def _find_prompt_inputs(nodes: Dict[str, Dict[str, Any]]) -> List[str]:
    hits = set()
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            continue
        for k in inputs.keys():
            lk = str(k).lower()
            if lk in ("text", "prompt", "positive", "pos_prompt"):
                hits.add(str(k))
    return sorted(hits)


def _has_load_image(nodes: Dict[str, Dict[str, Any]]) -> bool:
    for node in nodes.values():
        ct = str(node.get("class_type", "")).lower()
        if ct in ("loadimage", "load_image"):
            return True
    return False


def _has_mask(nodes: Dict[str, Dict[str, Any]]) -> bool:
    # Маска может быть где угодно, ищем по тексту
    text = json.dumps(nodes, ensure_ascii=False).lower()
    return "mask" in text


def _collect_outputs(nodes: Dict[str, Dict[str, Any]]) -> List[str]:
    """
    В workflow JSON outputs обычно не перечислены явно.
    Ищем по нодам сохранения (SaveImage / VideoCombine и т.п.)
    """
    outs: List[str] = []
    for nid, node in nodes.items():
        ct = str(node.get("class_type", ""))
        lct = ct.lower()

        if lct in ("saveimage", "save_image"):
            outs.append(f"{nid}: {ct} -> images[]")
            continue

        if "videocombine" in lct or ("video" in lct and ("combine" in lct or "save" in lct)):
            outs.append(f"{nid}: {ct} -> video")
            continue

        if "save" in lct and ("gif" in lct or "anim" in lct):
            outs.append(f"{nid}: {ct} -> animation")
            continue

    return outs


def _md_escape_cell(text: str) -> str:
    # Чтобы не ломать таблицу
    return (text or "").replace("|", "\\|").replace("\n", " ")


def main() -> int:
    if not WF_DIR.exists():
        raise SystemExit(f"Workflows dir not found: {WF_DIR}")

    files = sorted(WF_DIR.glob("*.json"), key=lambda p: p.name.lower())

    details: List[Tuple[str, str, bool, bool, List[str], List[str]]] = []

    for p in files:
        data = _load_workflow_json(p)
        nodes_raw = data.get("nodes") if isinstance(data, dict) else None
        nodes = _normalize_nodes(nodes_raw)
        kind = _guess_kind(nodes)
        has_load = _has_load_image(nodes)
        has_mask = _has_mask(nodes)
        prompts = _find_prompt_inputs(nodes)
        outs = _collect_outputs(nodes)

        details.append((p.stem, kind, has_load, has_mask, prompts, outs))

    # ДЕТЕРМИНИРОВАННЫЙ ВЫВОД: никакой даты/времени/случайностей
    lines: List[str] = []
    lines.append("# 📚 Справочник по Workflows (img_bot)")
    lines.append("")
    lines.append("Этот файл генерируется скриптом `tools/gen_workflows_reference.py` на основе JSON из папки `workflows/`.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📋 Сводная таблица")
    lines.append("")
    lines.append("| Workflow | Тип | LoadImage | Mask | Prompt-поля | Выходы (по нодам) |")
    lines.append("|---|---:|:---:|:---:|---|---|")

    for name, kind, has_load, has_mask, prompts, outs in details:
        lines.append(
            "| `{}` | {} | {} | {} | {} | {} |".format(
                name,
                _md_escape_cell(kind),
                "✅" if has_load else "—",
                "✅" if has_mask else "—",
                _md_escape_cell(", ".join(prompts) if prompts else "—"),
                _md_escape_cell("; ".join(outs) if outs else "—"),
            )
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 📄 Подробности по каждому workflow")
    lines.append("")

    for name, kind, has_load, has_mask, prompts, outs in details:
        lines.append(f"### `{name}.json`")
        lines.append("")
        lines.append(f"- **Тип:** `{kind}`")
        lines.append(f"- **LoadImage:** {'да' if has_load else 'нет'}")
        lines.append(f"- **Mask:** {'да' if has_mask else 'нет'}")
        lines.append(f"- **Prompt-поля:** {', '.join(prompts) if prompts else 'не найдено автоматически'}")
        lines.append("- **Выходы (эвристика по нодам):**")
        if outs:
            for o in outs:
                lines.append(f"  - {o}")
        else:
            lines.append("  - не найдено автоматически (проверь ноды сохранения)")
        lines.append("")
        lines.append("**Заметки:** дополни вручную (VRAM, время, точные входы), если требуется.")
        lines.append("")
        lines.append("---")
        lines.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines), encoding="utf-8")

    print(f"OK: wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

