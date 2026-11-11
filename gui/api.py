"""Small blocking JSON client for the loopback GUI backend.

Calls run in a worker thread; GTK callbacks are scheduled by the UI helper.
No third-party HTTP library is needed.
"""

from __future__ import annotations

import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any


class ApiError(RuntimeError):
    def __init__(self, status: int, detail: Any, path: str = "") -> None:
        if isinstance(detail, dict):
            message = str(
                detail.get("message")
                or detail.get("detail")
                or detail.get("reason")
                or f"HTTP {status}"
            )
        else:
            message = str(detail or f"HTTP {status}")
        super().__init__(message)
        self.status = status
        self.detail = detail
        self.path = path


class ApiClient:
    def __init__(
        self, base_url: str, *, timeout: float = 30.0, token: str = ""
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.token = str(token or "")
        # Never route 127.0.0.1 through a user's HTTP proxy.
        self._opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
        )

    # ------------------------------------------------------------------
    # Core request
    # ------------------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        body: Any = None,
        *,
        timeout: float | None = None,
        raw: bool = False,
        headers: dict[str, str] | None = None,
    ) -> Any:
        url = path if path.startswith("http") else self.base_url + path
        data: bytes | None = None
        request_headers = {"Accept": "application/json"}
        if self.token:
            request_headers["Authorization"] = f"Bearer {self.token}"
        if headers:
            request_headers.update(headers)
        if body is not None:
            if isinstance(body, (bytes, bytearray)):
                data = bytes(body)
            else:
                data = json.dumps(body, ensure_ascii=False).encode("utf-8")
                request_headers["Content-Type"] = "application/json; charset=utf-8"
        request = urllib.request.Request(
            url, data=data, headers=request_headers, method=method.upper()
        )
        try:
            with self._opener.open(
                request, timeout=float(timeout or self.timeout)
            ) as response:
                payload = response.read()
                if raw:
                    return payload
                content_type = response.headers.get("Content-Type", "")
                if "application/json" in content_type or payload[:1] in (b"{", b"["):
                    try:
                        return json.loads(payload.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        return payload.decode("utf-8", errors="replace")
                return payload.decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raw_body = exc.read()
            detail: Any = raw_body.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(detail)
                if isinstance(parsed, dict) and "detail" in parsed:
                    detail = parsed["detail"]
                else:
                    detail = parsed
            except (json.JSONDecodeError, TypeError):
                pass
            raise ApiError(exc.code, detail, path) from None
        except urllib.error.URLError as exc:
            raise ApiError(0, f"无法连接到本地控制服务：{exc.reason}", path) from None
        except TimeoutError:
            raise ApiError(0, "请求超时，请稍后重试", path) from None

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, body: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, body, **kwargs)

    def patch(self, path: str, body: Any = None, **kwargs: Any) -> Any:
        return self.request("PATCH", path, body, **kwargs)

    def put(self, path: str, body: Any = None, **kwargs: Any) -> Any:
        return self.request("PUT", path, body, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    def raw(self, path: str, **kwargs: Any) -> bytes:
        return self.request("GET", path, raw=True, **kwargs)

    # ------------------------------------------------------------------
    # Multipart upload
    # ------------------------------------------------------------------
    def upload(
        self,
        path: str,
        *,
        fields: dict[str, str] | None = None,
        files: list[tuple[str, str, bytes, str]] | None = None,
        timeout: float | None = None,
    ) -> Any:
        boundary = "----KarenGUI" + uuid.uuid4().hex
        chunks: list[bytes] = []
        for key, value in (fields or {}).items():
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{key}"\r\n\r\n'
                    f"{value}\r\n"
                ).encode()
            )
        for field, filename, data, content_type in files or []:
            safe_name = filename.replace('"', "_")
            chunks.append(
                (
                    f"--{boundary}\r\n"
                    f'Content-Disposition: form-data; name="{field}"; '
                    f'filename="{safe_name}"\r\n'
                    f"Content-Type: {content_type}\r\n\r\n"
                ).encode()
            )
            chunks.append(data)
            chunks.append(b"\r\n")
        chunks.append(f"--{boundary}--\r\n".encode())
        payload = b"".join(chunks)
        return self.request(
            "POST",
            path,
            payload,
            timeout=timeout,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    def upload_file(
        self,
        path: str,
        file_path: str | Path,
        *,
        field: str = "file",
        fields: dict[str, str] | None = None,
        timeout: float | None = None,
    ) -> Any:
        source = Path(file_path)
        mime = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        return self.upload(
            path,
            fields=fields,
            files=[(field, source.name, source.read_bytes(), mime)],
            timeout=timeout,
        )


def q(value: Any) -> str:
    return urllib.parse.quote(str(value), safe="")


__all__ = ["ApiClient", "ApiError", "q"]
