#!/usr/bin/env python3
"""Issue one HTTP probe from the client network namespace."""

import sys
import urllib.error
import urllib.request


try:
    with urllib.request.urlopen("http://10.112.1.10:8080/", timeout=4) as response:
        print(f"HTTP {response.status}: {response.read().decode()}")
except (TimeoutError, urllib.error.URLError) as exc:
    print(f"HTTP probe failed: {exc}")
    raise SystemExit(1)
