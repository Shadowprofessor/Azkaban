"""Stream a browser-selected file batch into a temporary local audit."""

import json
import re
from pathlib import Path, PureWindowsPath
from tempfile import TemporaryDirectory

from .archive_signals import KNOWN_PLATFORMS
from .audit import LOOSE_SUFFIXES, MAX_FILE, audit


IMPORT_LIMIT = 512 * 1024 * 1024
FILE_LIMIT = 8
MANIFEST_LIMIT = 16 * 1024
SUFFIXES = LOOSE_SUFFIXES | {".zip"}
RESERVED_STEM = re.compile(r"^(?:con|prn|aux|nul|com[1-9¹²³]|lpt[1-9¹²³])$", re.I)


def read_exact(stream, length):
    data = stream.read(length)
    if len(data) != length:
        raise ValueError("The upload was incomplete. Select the files again.")
    return data


def validate_member(item):
    if not isinstance(item, dict) or set(item) != {"name", "size"}:
        raise ValueError("Invalid file details.")
    name = item["name"]
    size = item["size"]
    if (not isinstance(name, str) or not 1 <= len(name) <= 200 or name != name.strip()
            or name.endswith(".") or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in name)
            or RESERVED_STEM.fullmatch(name.split(".", 1)[0].rstrip())):
        raise ValueError("A selected file has an unsupported filename.")
    suffix = PureWindowsPath(name).suffix.lower()
    if suffix not in SUFFIXES:
        raise ValueError("Select ZIP archives or supported JSON, CSV, HTML, JS, or VCF export files.")
    limit = IMPORT_LIMIT if suffix == ".zip" else MAX_FILE
    if type(size) is not int or not 0 < size <= limit:
        raise ValueError("A selected file is empty or exceeds its size limit.")
    return name, size


def import_batch(stream, length):
    if not 4 < length <= IMPORT_LIMIT + MANIFEST_LIMIT + 4:
        raise ValueError("Select up to eight files with a combined size of 512 MiB or less.")
    manifest_length = int.from_bytes(read_exact(stream, 4), "big")
    if not 0 < manifest_length <= min(MANIFEST_LIMIT, length - 4):
        raise ValueError("Invalid upload metadata.")
    manifest = json.loads(read_exact(stream, manifest_length))
    if not isinstance(manifest, dict) or set(manifest) != {"files", "platform"}:
        raise ValueError("Invalid upload metadata.")
    files = manifest["files"]
    platform = manifest["platform"]
    if platform is not None and platform not in KNOWN_PLATFORMS[:-1]:
        raise ValueError("Choose a supported platform hint.")
    if not isinstance(files, list) or not 1 <= len(files) <= FILE_LIMIT:
        raise ValueError("Choose between one and eight export files.")
    members = [validate_member(item) for item in files]
    total = sum(size for _, size in members)
    if total > IMPORT_LIMIT or length != total + manifest_length + 4:
        raise ValueError("The file sizes do not match the upload or exceed its limit.")

    with TemporaryDirectory(prefix="ghostprint-import-") as directory:
        sources = []
        for index, (name, remaining) in enumerate(members, 1):
            folder = Path(directory) / str(index)
            folder.mkdir()
            path = folder / name
            with path.open("wb") as output:
                while remaining:
                    chunk = read_exact(stream, min(remaining, 1024 * 1024))
                    output.write(chunk)
                    remaining -= len(chunk)
            sources.append((path, platform))
        return audit(sources)
