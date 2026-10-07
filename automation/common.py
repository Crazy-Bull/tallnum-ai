from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import time
from pathlib import Path


def link_or_copy(source, target):
    """Share a table when supported, otherwise copy across disks/non-NTFS storage."""
    try:
        os.link(source,target)
    except OSError as error:
        if getattr(error,'winerror',None) not in (1,5,17,50) and error.errno not in (18,95):
            raise
        shutil.copy2(source,target)


def fingerprint(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path, value, *, indent=2):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    # Stream large replay/checkpoint records instead of building a second
    # full-sized string and the encoder's intermediate chunk list in memory.
    with temporary.open('w',encoding='utf-8') as file:
        json.dump(value,file,ensure_ascii=False,indent=indent,allow_nan=False)
    # Windows readers/antivirus can briefly hold the destination without
    # delete sharing. Retry the atomic rename, preserving the old checkpoint.
    for attempt in range(8):
        try:
            os.replace(temporary,path)
            break
        except PermissionError as error:
            if getattr(error,'winerror',None) not in (5,32) or attempt==7:raise
            time.sleep(min(.03*2**attempt,.3))


def finite_or_none(value):
    return value if math.isfinite(value) else None


def event(kind, **data):
    print(json.dumps({'event': kind, **data}, ensure_ascii=False, allow_nan=False), flush=True)


def execution_fingerprint():
    root = Path(__file__).parent
    h = hashlib.sha256()
    for name in ('game.py','runtime.py','execution.py','route_synthesis.py','route_baseline.py','route_continuation.py','controller_lock.py','route_runtime.py','route_search.py','route_variants.py','route_cli.py','browser.py','existing_browser.py','resume.py','validation.py','planner.py','library.py','certify.py','aggressive.py','native_policy.cpp','common.py'):
        h.update(name.encode())
        h.update((root/name).read_bytes())
    native = root.parent/'desktop/native/tallnum_automation.exe'
    if not native.exists():
        native = root.parent/'native/tallnum_automation.exe'
    if native.exists():
        h.update(fingerprint(native).encode())
    routes_native = native.with_name('tallnum_automation_routes.exe')
    if routes_native.exists():
        h.update(fingerprint(routes_native).encode())
    return h.hexdigest()
