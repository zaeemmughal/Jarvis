"""Small HTTP helpers on top of urllib (no `requests` dependency)."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (compatible; JARVIS-Desktop-Assistant/2.0)"


class NetError(Exception):
    def __init__(self, msg: str, status: int | None = None):
        super().__init__(msg)
        self.status = status


def _open(req: urllib.request.Request, timeout: float) -> bytes:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:800]
        except Exception:
            pass
        raise NetError("HTTP %s: %s" % (e.code, body), e.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise NetError(str(getattr(e, "reason", e))) from None


def get_bytes(url: str, params: dict | None = None, timeout: float = 8, headers: dict | None = None) -> bytes:
    if params:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    h = {"User-Agent": UA}
    h.update(headers or {})
    return _open(urllib.request.Request(url, headers=h), timeout)


def get_json(url: str, params: dict | None = None, timeout: float = 8, headers: dict | None = None):
    return json.loads(get_bytes(url, params, timeout, headers).decode("utf-8", "replace"))


def post_json(url: str, payload: dict, timeout: float = 25, headers: dict | None = None):
    h = {"User-Agent": UA, "Content-Type": "application/json"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=h, method="POST")
    return json.loads(_open(req, timeout).decode("utf-8", "replace"))


def post_stream(url: str, payload: dict, timeout: float = 25, headers: dict | None = None):
    """POST a JSON body and yield each server-sent-event JSON object as it arrives (OpenAI-style `data: {...}` lines).
    Closing the generator closes the connection, which is how a \"stop\" cuts a long answer short."""
    h = {"User-Agent": UA, "Content-Type": "application/json", "Accept": "text/event-stream"}
    h.update(headers or {})
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=h, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:800]
        except Exception:
            pass
        raise NetError("HTTP %s: %s" % (e.code, body), e.code) from None
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise NetError(str(getattr(e, "reason", e))) from None
    try:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                yield json.loads(data)
            except ValueError:
                continue
    except (socket.timeout, TimeoutError, ConnectionError, OSError) as e:
        raise NetError("stream interrupted: %s" % e) from None
    finally:
        try:
            resp.close()
        except Exception:
            pass


def multipart(fields: dict, files: dict) -> tuple[bytes, str]:
    """Build a multipart/form-data body. files = {name: (filename, bytes, content_type)}. Returns (body, content_type)."""
    import uuid
    boundary = "----jarvis" + uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"\r\n\r\n%s\r\n" % (boundary, k, v)).encode("utf-8"))
    for k, (fname, data, ctype) in files.items():
        out.append(("--%s\r\nContent-Disposition: form-data; name=\"%s\"; filename=\"%s\"\r\nContent-Type: %s\r\n\r\n"
                    % (boundary, k, fname, ctype)).encode("utf-8"))
        out.append(data)
        out.append(b"\r\n")
    out.append(("--%s--\r\n" % boundary).encode("utf-8"))
    return b"".join(out), "multipart/form-data; boundary=" + boundary


def post_multipart(url: str, fields: dict, files: dict, timeout: float = 25, headers: dict | None = None):
    body, ctype = multipart(fields, files)
    h = {"User-Agent": UA, "Content-Type": ctype}
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method="POST")
    return json.loads(_open(req, timeout).decode("utf-8", "replace"))


def is_online(timeout: float = 2.0) -> bool:
    for host in (("1.1.1.1", 443), ("8.8.8.8", 53)):
        try:
            socket.create_connection(host, timeout).close()
            return True
        except OSError:
            continue
    return False
