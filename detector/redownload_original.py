"""Safely redownload AI Hub file 48980 and replace a damaged source ZIP.

The API key is read from data/.aihub_api_key (mode 0600). Download and assembly
files are kept on failure so work can be resumed, then removed on success.
"""

import os
import re
import stat
import tarfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
KEY_FILE = DATA / ".aihub_api_key"
TAR_FILE = DATA / "download_48980.tar"
PARTIAL_TAR = DATA / "download_48980.tar.partial"
ZIP_PREFIX = "원천데이터11.zip"
API_URL = "https://api.aihub.or.kr/down/0.6/172.do?fileSn=48980"


def check_tar(path):
    """Return ordered parts after checking TAR footer and consecutive offsets."""
    if not path.exists() or path.stat().st_size < 1024:
        raise ValueError("TAR is missing or too short")
    with path.open("rb") as source:
        source.seek(-1024, os.SEEK_END)
        if source.read() != bytes(1024):
            raise ValueError("TAR has no complete end marker")
    with tarfile.open(path, "r:") as archive:
        parts = []
        for member in archive.getmembers():
            match = re.search(r"/(원천데이터11\.zip)\.part(\d+)$", member.name)
            if member.isfile() and match:
                parts.append((int(match.group(2)), member))
        parts.sort(key=lambda pair: pair[0])
        if not parts or parts[0][0] != 0:
            raise ValueError("TAR does not contain the first ZIP part")
        for (offset, member), (next_offset, _) in zip(parts, parts[1:]):
            if offset + member.size != next_offset:
                raise ValueError(f"Missing ZIP bytes after part {offset}")
        return parts


def read_key():
    if not KEY_FILE.exists():
        raise FileNotFoundError(f"Place the AI Hub API key in {KEY_FILE} (mode 0600)")
    if stat.S_IMODE(KEY_FILE.stat().st_mode) & 0o077:
        raise PermissionError(f"Restrict {KEY_FILE} to mode 0600")
    key = KEY_FILE.read_text(encoding="utf-8").strip()
    if not key:
        raise ValueError("AI Hub API key file is empty")
    return key


def download():
    if TAR_FILE.exists():
        check_tar(TAR_FILE)
        return
    key = read_key()
    offset = PARTIAL_TAR.stat().st_size if PARTIAL_TAR.exists() else 0
    headers = {"apikey": key}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(API_URL, headers=headers)
    print(f"Downloading AI Hub file 48980 from byte {offset:,}", flush=True)
    with urllib.request.urlopen(request, timeout=120) as response:
        if offset:
            expected_prefix = f"bytes {offset}-"
            if response.status == 200:
                # AI Hub currently ignores Range. Rewrite the partial file from
                # the beginning so resumed bytes are never appended twice.
                print("AI Hub did not support resume; restarting from byte 0", flush=True)
                offset = 0
            elif response.status != 206 or not response.headers.get("Content-Range", "").startswith(expected_prefix):
                raise ValueError("Unexpected response to byte-range resume")
        elif response.status != 200:
            raise ValueError(f"Unexpected HTTP status {response.status}")
        expected = response.headers.get("Content-Length")
        expected = int(expected) if expected else None
        received = 0
        with PARTIAL_TAR.open("ab" if offset else "wb") as output:
            while chunk := response.read(8 * 1024 * 1024):
                output.write(chunk)
                received += len(chunk)
                if received // (256 * 1024 * 1024) != (received - len(chunk)) // (256 * 1024 * 1024):
                    print(f"Received {offset + received:,} bytes", flush=True)
        if expected is not None and received != expected:
            raise IOError(f"Download stopped early: got {received:,} of {expected:,} requested bytes")
    check_tar(PARTIAL_TAR)
    PARTIAL_TAR.rename(TAR_FILE)


def assemble_and_verify(parts):
    target = next(DATA.rglob(ZIP_PREFIX), None)
    if target is None:
        raise FileNotFoundError("Original ZIP directory was not found")
    candidate = DATA / "원천데이터11.verified.zip.tmp"
    with tarfile.open(TAR_FILE, "r:") as archive, candidate.open("wb") as output:
        for offset, member in parts:
            print(f"Assembling ZIP part at byte {offset:,}", flush=True)
            source = archive.extractfile(member)
            if source is None:
                raise IOError(f"Cannot read TAR member {member.name}")
            remaining = member.size
            while remaining:
                chunk = source.read(min(8 * 1024 * 1024, remaining))
                if not chunk:
                    raise IOError(f"TAR member {member.name} ended early")
                output.write(chunk)
                remaining -= len(chunk)
    print("Checking every ZIP member and CRC", flush=True)
    with zipfile.ZipFile(candidate) as archive:
        count = len(archive.infolist())
        bad_member = archive.testzip()
        if bad_member is not None:
            raise zipfile.BadZipFile(f"Corrupt ZIP member: {bad_member}")
    damaged = target.with_name("원천데이터11.damaged.zip")
    if damaged.exists():
        raise FileExistsError(f"Preserved damaged ZIP already exists: {damaged}")
    target.rename(damaged)
    candidate.rename(target)
    damaged.unlink()
    TAR_FILE.unlink()
    print(f"Verified {count:,} ZIP entries; saved {target}", flush=True)


def main():
    for attempt in range(1, 11):
        try:
            download()
            break
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == 10:
                raise
            print(f"Server error {error.code}; retrying download ({attempt}/10)", flush=True)
        except (urllib.error.URLError, OSError, TimeoutError) as error:
            if attempt == 10:
                raise
            print(f"Connection interrupted; retrying download ({attempt}/10): {error}", flush=True)
        time.sleep(min(60, 10 * attempt))
    assemble_and_verify(check_tar(TAR_FILE))


if __name__ == "__main__":
    main()
