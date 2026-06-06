import os
import json
import hashlib
from config import HASH_FILE


def load_hashes():
    try:
        with open(HASH_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_hashes(h):
    os.makedirs(os.path.dirname(HASH_FILE), exist_ok=True)
    tmp = HASH_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(h, f)
    os.replace(tmp, HASH_FILE)


def file_hash(data):
    return hashlib.sha256(data).hexdigest()[:16]
