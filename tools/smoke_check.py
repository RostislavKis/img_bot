# -*- coding: utf-8 -*-
"""
Smoke-check инструмент для проверки здоровья ComfyUI API.
Проверяет основные endpoints и выдаёт понятный диагноз при ошибках.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

try:
    import requests
except Exception as e:
    print("ERROR: requests not installed. Install it: pip install requests", file=sys.stderr)
    raise


@dataclass
class CheckResult:
    ok: bool
    name: str
    detail: str
    extra: Optional[Dict[str, Any]] = None


def _get(url: str, timeout: float) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    try:
        r = requests.get(url, timeout=timeout)
        ct = (r.headers.get("content-type") or "").lower()
        if r.status_code != 200:
            return False, f"HTTP {r.status_code}", None
        if "application/json" in ct:
            try:
                return True, "OK", r.json()
            except Exception:
                return True, "OK (non-json body)", None
        return True, "OK", None
    except requests.exceptions.ConnectTimeout:
        return False, "connect timeout", None
    except requests.exceptions.ReadTimeout:
        return False, "read timeout", None
    except requests.exceptions.ConnectionError as e:
        return False, f"connection error: {e}", None
    except Exception as e:
        return False, f"error: {e}", None


def _summarize_system_stats(data: Optional[Dict[str, Any]]) -> str:
    if not data:
        return "no json"
    # ComfyUI обычно отдаёт разные структуры в зависимости от версии
    # Пытаемся достать полезное максимально безопасно
    try:
        # Иногда есть "system" / "devices" / "cuda" и т.п.
        text = json.dumps(data, ensure_ascii=False)
        # Короткая выжимка
        keys = list(data.keys())[:20]
        return f"json keys={keys}"
    except Exception:
        return "json (unparsed)"


def run_checks(base_url: str, timeout: float) -> list:
    base_url = base_url.rstrip("/")

    checks = []

    ok, detail, _ = _get(f"{base_url}/", timeout)
    checks.append(CheckResult(ok, "GET / (root)", detail))

    ok, detail, data = _get(f"{base_url}/system_stats", timeout)
    checks.append(CheckResult(ok, "GET /system_stats", f"{detail}; {_summarize_system_stats(data)}", data))

    # /queue — полезно, если очередь зависла
    ok, detail, data = _get(f"{base_url}/queue", timeout)
    checks.append(CheckResult(ok, "GET /queue", detail, data))

    # /object_info — проверка, что API живое и отдаёт инфу о нодах
    ok, detail, data = _get(f"{base_url}/object_info", timeout)
    checks.append(CheckResult(ok, "GET /object_info", detail, data))

    return checks


def main() -> int:
    ap = argparse.ArgumentParser(description="Smoke-check for img_bot / ComfyUI")
    ap.add_argument("--url", default=os.getenv("COMFY_URL", "http://127.0.0.1:8188"), help="ComfyUI base URL")
    ap.add_argument("--timeout", type=float, default=3.0, help="HTTP timeout seconds")
    ap.add_argument("--repeat", type=int, default=1, help="Repeat N times (useful for flaky startup)")
    ap.add_argument("--delay", type=float, default=0.5, help="Delay between repeats (seconds)")
    args = ap.parse_args()

    print(f"SMOKE: url={args.url} timeout={args.timeout}s repeat={args.repeat} delay={args.delay}s")

    last_checks = []
    for i in range(1, args.repeat + 1):
        if i > 1:
            time.sleep(args.delay)
        print(f"\n--- attempt {i}/{args.repeat} ---")
        last_checks = run_checks(args.url, args.timeout)

        any_fail = any(not c.ok for c in last_checks)
        for c in last_checks:
            mark = "OK " if c.ok else "FAIL"
            print(f"[{mark}] {c.name}: {c.detail}")

        if not any_fail:
            print("\nSMOKE: ✅ OK")
            return 0

    # Если сюда дошли — всё плохо
    print("\nSMOKE: ❌ NOT OK", file=sys.stderr)

    # Мини-диагноз (самое частое)
    root = next((c for c in last_checks if c.name.startswith("GET / (root)")), None)
    stats = next((c for c in last_checks if c.name.startswith("GET /system_stats")), None)
    if root and not root.ok:
        print("DIAG: base URL unreachable (ComfyUI not running / wrong URL / firewall).", file=sys.stderr)
    elif stats and not stats.ok:
        print("DIAG: ComfyUI reachable but /system_stats failing (version mismatch / plugin / proxy).", file=sys.stderr)
    else:
        print("DIAG: ComfyUI reachable but one of endpoints failing (/queue or /object_info).", file=sys.stderr)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
