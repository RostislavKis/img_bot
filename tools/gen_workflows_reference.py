# -*- coding: utf-8 -*-
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
WF_DIR = ROOT / "workflows"
OUT = ROOT / "docs" / "WORKFLOWS_REFERENCE.md"

VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".avi", ".gif"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}

def _guess_kind(nodes: dict) -> str:
    # По нодам SaveImage / VideoCombine / SaveAnimated / ffmpeg и т.п.
    text = json.dumps(nodes, ensure_ascii=False).lower()
    if "vhs_videocombine" in text or "video" in text and ("mp4" in text or "webm" in text):
        return "video"
    if "saveimage" in text or "images" in text:
        return "image"
    return "unknown"

def _find_prompt_inputs(nodes: dict) -> list[str]:
    hits = set()
    for nid, node in (nodes or {}).items():
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        for k in inputs.keys():
            lk = str(k).lower()
            if lk in ("text", "prompt", "positive", "pos_prompt"):
                hits.add(k)
    return sorted(hits) if hits else []

def _has_load_image(nodes: dict) -> bool:
    for node in (nodes or {}).values():
        if isinstance(node, dict) and str(node.get("class_type","")).lower() in ("loadimage","load_image"):
            return True
    return False

def _has_mask(nodes: dict) -> bool:
    text = json.dumps(nodes, ensure_ascii=False).lower()
    return "mask" in text

def _collect_outputs(nodes: dict) -> list[str]:
    # В JSON Comfy обычно outputs не перечислены явно, поэтому ищем SaveImage/VideoCombine
    outs = []
    for nid, node in (nodes or {}).items():
        if not isinstance(node, dict):
            continue
        ct = str(node.get("class_type",""))
        lct = ct.lower()
        if lct in ("saveimage","save_image"):
            outs.append(f"{nid}: {ct} -> images[]")
        elif "videocombine" in lct or "video" in lct and ("combine" in lct or "save" in lct):
            outs.append(f"{nid}: {ct} -> video")
        elif "save" in lct and ("gif" in lct or "anim" in lct):
            outs.append(f"{nid}: {ct} -> animation")
    return outs

def main() -> int:
    if not WF_DIR.exists():
        raise SystemExit(f"Workflows dir not found: {WF_DIR}")
    files = sorted(WF_DIR.glob("*.json"), key=lambda p: p.name.lower())

    lines = []
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

    details = []

    for p in files:
        data = json.loads(p.read_text(encoding="utf-8"))
        nodes = data.get("nodes") if isinstance(data, dict) else None
        kind = _guess_kind(nodes or {})
        has_load = _has_load_image(nodes or {})
        has_mask = _has_mask(nodes or {})
        prompts = _find_prompt_inputs(nodes or {})
        outs = _collect_outputs(nodes or {})
        lines.append(f"| `{p.stem}` | {kind} | {'✅' if has_load else '—'} | {'✅' if has_mask else '—'} | {', '.join(prompts) if prompts else '—'} | {'; '.join(outs) if outs else '—'} |")

        details.append((p.stem, kind, has_load, has_mask, prompts, outs))

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
        lines.append(f"- **Выходы (эвристика по нодам):**")
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
    raise SystemExit(main())
