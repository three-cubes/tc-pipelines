"""Bounded raw GitHub downloads; ANSI log bytes never pass through gh's renderer."""

import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

try:  # Executable both as ``python assurance/...`` and as a package module.
    from .receipt import ReceiptError, read
except ImportError:  # pragma: no cover - exercised by the workflow entrypoint.
    from receipt import ReceiptError, read

MAX_DOWNLOAD = 16 * 1024 * 1024


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urllib.parse.urlsplit(req.full_url).netloc != urllib.parse.urlsplit(newurl).netloc:
            redirected.remove_header("Authorization")
        return redirected


def sanitise(value):
    value = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", "", value)
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    return "".join(c for c in value if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127))


def download(url, destination):
    """Retain raw bytes and bounded failure diagnostics without printing credentials."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "tc-assurance"}
    if urllib.parse.urlsplit(url).netloc == "api.github.com":
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise ReceiptError("GitHub evidence download requires an authorised token")
        headers["Authorization"] = "Bearer " + token
    stderr = destination.with_suffix(".stderr")
    try:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.build_opener(SafeRedirect()).open(request, timeout=30) as response:
            data = response.read(MAX_DOWNLOAD + 1)
        if len(data) > MAX_DOWNLOAD:
            raise ReceiptError("download exceeds evidence size limit")
        destination.write_bytes(data)
        stderr.write_text("download completed\n")
        return data
    except (OSError, ValueError) as error:
        # Do not retain exception URLs: a redirect can contain signed credentials.
        diagnostic = (
            f"download failed: {type(error).__name__} status={getattr(error, 'code', 'unavailable')}\n"
        )
        if isinstance(error, urllib.error.HTTPError):
            destination.with_suffix(".failure-body").write_bytes(error.read(4096))
        stderr.write_text(diagnostic)
        raise ReceiptError(diagnostic.strip()) from error


def download_log(url, destination):
    raw = download(url, destination.with_suffix(".raw"))
    return sanitise(raw.decode("utf-8", errors="replace"))


def archive_member(archive, name):
    try:
        with zipfile.ZipFile(archive) as source:
            members = [item for item in source.infolist() if item.filename == name]
            if len(members) != 1 or members[0].file_size > MAX_DOWNLOAD:
                raise ReceiptError("missing, duplicate or oversized native artifact member")
            return source.read(members[0])
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError) as error:
        raise ReceiptError("invalid native artifact archive") from error


def validate_mutation(path):
    result = read(Path(path))
    if result != {"status": "pass", "original_exit": 0, "mutant_exit": 1, "killed": 1}:
        raise ReceiptError("native mutation result did not terminally pass")
    return result
