"""Export every collection in the Mongo database to JSONL. No arguments needed.

    pip install pymongo python-dotenv
    python Export.py

Reads MONGODB_URI from .env in the same folder. Writes one <collection>.jsonl per
collection into .\export\, UTF-8, one JSON document per line.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

try:
    from bson import json_util
    from dotenv import load_dotenv
    from pymongo import MongoClient
except ImportError as exc:
    sys.exit(f"Missing package: {exc.name}\n  pip install pymongo python-dotenv")

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "export"
DROP_FIELDS = {"_id"}


def to_plain(doc: dict) -> dict:
    clean = {k: v for k, v in doc.items() if k not in DROP_FIELDS}
    return json.loads(json_util.dumps(clean, json_options=json_util.RELAXED_JSON_OPTIONS))


def resolve_db(client: MongoClient):
    """Use the db from the URI if it's real, otherwise pick the only user database."""
    try:
        db = client.get_default_database()
        if db is not None and db.name not in ("admin", "local", "config", "your_database_name"):
            return db
    except Exception:
        pass

    names = [n for n in client.list_database_names()
             if n not in ("admin", "local", "config")]
    if not names:
        sys.exit("No user databases found on this cluster.")
    if len(names) > 1:
        print(f"Found several databases: {', '.join(names)} -- using '{names[0]}'")
    return client[names[0]]


def main() -> int:
    load_dotenv(HERE / ".env")
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        sys.exit(f"MONGODB_URI not found in {HERE / '.env'}")

    print("connecting...")
    client = MongoClient(uri, serverSelectionTimeoutMS=20000)
    try:
        client.admin.command("ping")
    except Exception as exc:
        sys.exit(f"Could not connect: {exc}\n"
                 "Check the password and that your IP is allowed in Atlas Network Access.")

    db = resolve_db(client)
    collections = db.list_collection_names()
    if not collections:
        sys.exit(f"Database '{db.name}' has no collections.")

    OUT_DIR.mkdir(exist_ok=True)
    print(f"database: {db.name}")
    print(f"collections: {', '.join(collections)}\n")

    grand_total = 0
    for name in collections:
        coll = db[name]
        total = coll.estimated_document_count()
        out = OUT_DIR / f"{name}.jsonl"
        written = 0
        with out.open("w", encoding="utf-8", newline="\n") as fh:
            for doc in coll.find({}, batch_size=1000):
                fh.write(json.dumps(to_plain(doc), ensure_ascii=False) + "\n")
                written += 1
                if written % 1000 == 0:
                    print(f"  {name}: {written}/{total}")
        grand_total += written
        print(f"{name}: {written} lines -> {out}")

    print(f"\ndone. {grand_total} documents in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())