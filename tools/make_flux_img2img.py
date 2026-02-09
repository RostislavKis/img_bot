#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Генератор img2img workflow из txt2img FLUX workflow.
Заменяет EmptyLatentImage на LoadImage + VAEEncode.
"""
import argparse, json, os


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: str, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def next_id(nodes: dict) -> str:
    mx = 0
    for k in nodes.keys():
        try:
            mx = max(mx, int(k))
        except Exception:
            pass
    return str(mx + 1)


def find_first_node_id(nodes: dict, class_types: tuple[str, ...]) -> str | None:
    for nid, n in nodes.items():
        if isinstance(n, dict) and n.get("class_type") in class_types:
            return nid
    return None


def find_any_vae_link(nodes: dict):
    # Берём подключение VAE из любого VAEDecode, чтобы VAEEncode получил тот же VAE
    for nid, n in nodes.items():
        if not isinstance(n, dict):
            continue
        ct = n.get("class_type")
        if ct in ("VAEDecode", "VAEDecodeTiled"):
            inputs = n.get("inputs") or {}
            if "vae" in inputs:
                return inputs["vae"]
    return None


def replace_links(nodes: dict, from_id: str, to_id: str):
    for nid, n in nodes.items():
        if not isinstance(n, dict):
            continue
        inputs = n.get("inputs")
        if not isinstance(inputs, dict):
            continue
        for k, v in list(inputs.items()):
            if isinstance(v, list) and len(v) == 2 and str(v[0]) == str(from_id):
                inputs[k] = [to_id, 0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", dest="out", required=True)
    ap.add_argument("--default-image", dest="default_image", default="tg_photo.png")
    args = ap.parse_args()

    wf = load_json(args.inp)
    nodes = wf

    # 1) Находим EmptyLatentImage (который использовался в txt2img)
    empty_latent_id = find_first_node_id(nodes, ("EmptyLatentImage", "EmptyLatent"))
    if not empty_latent_id:
        raise SystemExit("Не найден EmptyLatentImage/EmptyLatent в workflow (нечего заменить на img2img).")

    # 2) Достаём VAE линк из VAEDecode
    vae_link = find_any_vae_link(nodes)
    if not vae_link:
        raise SystemExit("Не найден VAEDecode с входом 'vae' (нужно, чтобы подключить VAEEncode).")

    # 3) Добавляем LoadImage
    load_id = next_id(nodes)
    nodes[load_id] = {
        "class_type": "LoadImage",
        "inputs": {
            "image": args.default_image
        }
    }

    # 4) Добавляем VAEEncode (pixels от LoadImage, vae как у VAEDecode)
    enc_id = next_id(nodes)
    nodes[enc_id] = {
        "class_type": "VAEEncode",
        "inputs": {
            "pixels": [load_id, 0],
            "vae": vae_link
        }
    }

    # 5) Переключаем все связи с EmptyLatentImage → VAEEncode.latent
    replace_links(nodes, empty_latent_id, enc_id)

    save_json(args.out, wf)
    print(f"OK: создан img2img workflow: {args.out}")


if __name__ == "__main__":
    main()
