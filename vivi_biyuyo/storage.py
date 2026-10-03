from __future__ import annotations
import json, os, tempfile
from pathlib import Path

def atomic_write(path: Path, text: str):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix="."+path.name+".")
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f: f.write(text)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def read_json(path: Path, default=None):
    if not Path(path).exists(): return default
    try: return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError,ValueError,TypeError): return default

def write_json(path: Path, data):
    atomic_write(path,json.dumps(data,indent=2,allow_nan=False))

def append_jsonl(path: Path, record: dict):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("a",encoding="utf-8") as f:
        f.write(json.dumps(record,separators=(",",":"),allow_nan=False)+"\n")
