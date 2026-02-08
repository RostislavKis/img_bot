# -*- coding: utf-8 -*-
"""
ComfyUI API smoke-check инструмент (без внешних зависимостей).
Использует только стандартную библиотеку Python (urllib).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.error import URLError, HTTPError
from urllib.request import Request, urlopen


@dataclass
class CheckResult:
    ok: bool
    status: Optional[int]
    elapsed_ms: int
    error: Optional[str]
    data: Optional[Any]


def _now_ms() -> int:
    return int(time.time() * 1000)


def _join_url(base: str, path: str) -> str:
    base = (base or "").rstrip("/")
    path = (path or "").lstrip("/")
    return f"{base}/{path}"


def _http_json(url: str, timeout: float) -> CheckResult:
    t0 = _now_ms()
    try:
        req = Request(url, headers={"User-Agent": "img_bot-smoke_check/1.0"})
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", None)
            raw = resp.read()
            elapsed = _now_ms() - t0

            # Пытаемся распарсить JSON (ComfyUI почти везде JSON)
            try:
                txt = raw.decode("utf-8", errors="replace")
                data = json.loads(txt) if txt.strip() else None
            except Exception:
                data = None

            return CheckResult(ok=True, status=status, elapsed_ms=elapsed, error=None, data=data)

    except HTTPError as e:
        elapsed = _now_ms() - t0
        return CheckResult(ok=False, status=getattr(e, "code", None), elapsed_ms=elapsed, error=f"HTTPError: {e}", data=None)
    except URLError as e:
        elapsed = _now_ms() - t0
        return CheckResult(ok=False, status=None, elapsed_ms=elapsed, error=f"URLError: {e}", data=None)
    except Exception as e:
        elapsed = _now_ms() - t0
        return CheckResult(ok=False, status=None, elapsed_ms=elapsed, error=f"Exception: {e}", data=None)


def _print_endpoint(name: str, url: str, res: CheckResult) -> None:
    if res.ok:
        print(f"✅ {name}: {res.status} ({res.elapsed_ms} ms)  {url}")
    else:
        st = res.status if res.status is not None else "-"
        print(f"❌ {name}: {st} ({res.elapsed_ms} ms)  {url}")
        if res.error:
            print(f"   ↳ {res.error}")


def _summarize(name: str, res: CheckResult) -> None:
    # Короткие полезные сводки по ответам
    if not res.ok or res.data is None:
        return

    try:
        if name == "system_stats" and isinstance(res.data, dict):
            keys = list(res.data.keys())
            print(f"   ↳ keys: {keys[:20]}{' ...' if len(keys) > 20 else ''}")

        if name == "queue" and isinstance(res.data, dict):
            # ComfyUI /queue обычно содержит queue_running/queue_pending
            for k in ("queue_running", "queue_pending"):
                if k in res.data:
                    v = res.data.get(k)
                    if isinstance(v, list):
                        print(f"   ↳ {k}: {len(v)} item(s)")
                    else:
                        print(f"   ↳ {k}: {type(v).__name__}")

        if name == "object_info":
            # Обычно большой словарь нод. Покажем количество.
            if isinstance(res.data, dict):
                print(f"   ↳ nodes: {len(res.data)}")
    except Exception:
        # Никогда не падаем из-за печати
        return


def run_once(base_url: str, timeout: float) -> Tuple[bool, Dict[str, CheckResult]]:
    urls = {
        "system_stats": _join_url(base_url, "system_stats"),
        "queue": _join_url(base_url, "queue"),
        "object_info": _join_url(base_url, "object_info"),
    }

    results: Dict[str, CheckResult] = {}
    overall_ok = True

    for name, url in urls.items():
        res = _http_json(url, timeout=timeout)
        results[name] = res
        _print_endpoint(name, url, res)
        _summarize(name, res)
        overall_ok = overall_ok and res.ok

    return overall_ok, results


def main() -> int:
    p = argparse.ArgumentParser(description="ComfyUI API smoke-check (no external deps).")
    p.add_argument("--url", default="http://127.0.0.1:8188", help="Base ComfyUI URL, e.g. http://127.0.0.1:8188")
    p.add_argument("--repeat", type=int, default=1, help="How many times to repeat the check")
    p.add_argument("--delay", type=float, default=0.5, help="Delay between repeats (seconds)")
    p.add_argument("--timeout", type=float, default=3.0, help="HTTP timeout per request (seconds)")
    args = p.parse_args()

    base = (args.url or "").strip()
    if not base:
        print("ERROR: --url is empty", file=sys.stderr)
        return 2

    repeat = max(1, int(args.repeat))
    delay = max(0.0, float(args.delay))
    timeout = max(0.5, float(args.timeout))

    any_fail = False
    for i in range(1, repeat + 1):
        print(f"\n=== Smoke check {i}/{repeat} ===")
        ok, _ = run_once(base, timeout=timeout)
        if not ok:
            any_fail = True
        if i < repeat and delay > 0:
            time.sleep(delay)

    if any_fail:
        print("\nRESULT: ❌ NOT OK")
        return 1

    print("\nRESULT: ✅ OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
