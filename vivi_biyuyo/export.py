"""Regenerate deterministic research exports from the authoritative database."""

import argparse
import json
import sqlite3
from pathlib import Path
from .config import Config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    database = Config.from_env().state_dir / "journal.sqlite3"
    db = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    # One read transaction produces a consistent set of exports during live capture.
    db.execute("BEGIN")
    for (kind,) in db.execute("SELECT DISTINCT kind FROM effects"):
        if not kind.isidentifier():
            raise ValueError("Invalid effect kind")
        with (args.output / (kind + ".jsonl")).open("w", encoding="utf-8") as out:
            for (payload,) in db.execute(
                "SELECT payload FROM effects WHERE kind=? ORDER BY id", (kind,)
            ):
                out.write(payload + "\n")
    with (args.output / "raw_events.jsonl").open("w", encoding="utf-8") as out:
        for received, payload in db.execute(
            "SELECT received,payload FROM inbox ORDER BY id"
        ):
            out.write(
                json.dumps({"received_ms": received, "payload": json.loads(payload)})
                + "\n"
            )
    db.close()


if __name__ == "__main__":
    main()
