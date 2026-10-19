"""VLMClient: the one way the backend and agents talk to the Geo-VLM (Qwen2.5-VL).

Modes, picked from the environment (EVICHANGE_VLM):
  http    POST to a model server, e.g. notebooks/EviChange_vlm_server.ipynb running on a Colab
          GPU behind a tunnel. Needs VLM_URL (the tunnel's https URL) and VLM_TOKEN.
  replay  Answers come from a JSON file (VLM_REPLAY_FILE), keyed by prompt version + region,
          for tests and for re-showing recorded runs without a GPU.
  off     (default when VLM_URL is unset) every call raises VLMUnavailable.

Server contract (http mode):
  GET  {VLM_URL}/health                      -> {"model": "Qwen/Qwen2.5-VL-7B-Instruct"}
  POST {VLM_URL}/generate  Authorization: Bearer <token>
       {"prompt": str, "images": [base64 PNG, ...], "max_new_tokens": int}
                                             -> {"text": str, "model": str}
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path


class VLMUnavailable(RuntimeError):
    """No model server is configured or reachable."""


class VLMClient:
    def __init__(self, mode: str | None = None, url: str | None = None, token: str | None = None,
                 replay_file: str | None = None, timeout_s: float = 180):
        self.url = (url if url is not None else os.environ.get("VLM_URL", "")).rstrip("/")
        self.token = token if token is not None else os.environ.get("VLM_TOKEN", "")
        self.mode = mode or os.environ.get("EVICHANGE_VLM") or ("http" if self.url else "off")
        self.replay_file = replay_file or os.environ.get("VLM_REPLAY_FILE", "")
        self.timeout_s = timeout_s
        self._replay: dict | None = None
        self._model: str | None = None
        self._status: tuple[float, dict] | None = None   # (time, result): /health is asked at most every STATUS_TTL_S

    STATUS_TTL_S = 30

    # ---------- status ----------
    def status(self) -> dict:
        """{"available": bool, "mode": str, "model": str | None, "detail": str}. Never raises."""
        if self.mode == "off":
            return {"available": False, "mode": "off", "model": None,
                    "detail": "No Geo-VLM server configured: set VLM_URL and VLM_TOKEN (see notebooks/EviChange_vlm_server.ipynb)."}
        if self.mode == "replay":
            ok = bool(self.replay_file) and Path(self.replay_file).exists()
            return {"available": ok, "mode": "replay", "model": "replay",
                    "detail": f"replaying {self.replay_file}" if ok else "VLM_REPLAY_FILE not found"}
        if self._status and time.time() - self._status[0] < self.STATUS_TTL_S:
            return self._status[1]
        try:
            body = self._request("GET", "/health", None, timeout=10)
            self._model = body.get("model")
            result = {"available": True, "mode": "http", "model": self._model, "detail": self.url}
        except VLMUnavailable as exc:
            result = {"available": False, "mode": "http", "model": None, "detail": str(exc)}
        self._status = (time.time(), result)
        return result

    # ---------- generation ----------
    def generate(self, prompt: str, images: list[bytes] = (), max_new_tokens: int = 400, replay_key: str | None = None) -> dict:
        """{"text": str, "model": str}. Raises VLMUnavailable when there is no usable model."""
        if self.mode == "off":
            raise VLMUnavailable(self.status()["detail"])
        if self.mode == "replay":
            if self._replay is None:
                if not self.replay_file or not Path(self.replay_file).exists():
                    raise VLMUnavailable("VLM_REPLAY_FILE not found")
                self._replay = json.loads(Path(self.replay_file).read_text(encoding="utf-8"))
            if replay_key not in self._replay:
                raise VLMUnavailable(f"no recorded answer for {replay_key!r}")
            return {"text": self._replay[replay_key], "model": "replay"}
        payload = {"prompt": prompt, "images": [base64.b64encode(i).decode("ascii") for i in images],
                   "max_new_tokens": max_new_tokens}
        try:
            body = self._request("POST", "/generate", payload, timeout=self.timeout_s)
        except VLMUnavailable:
            self._status = None   # re-check /health next time instead of trusting a stale "available"
            raise
        return {"text": body.get("text", ""), "model": body.get("model") or self._model or "unknown"}

    def _request(self, method: str, path: str, payload: dict | None, timeout: float) -> dict:
        if not self.url.startswith("https://") and not self.url.startswith("http://localhost") and not self.url.startswith("http://127.0.0.1"):
            raise VLMUnavailable("VLM_URL must be an https:// tunnel URL (or localhost)")
        data = json.dumps(payload).encode() if payload is not None else None
        req = urllib.request.Request(self.url + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            if exc.code in (401, 403):
                raise VLMUnavailable("the model server rejected VLM_TOKEN") from exc
            raise VLMUnavailable(f"model server error {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise VLMUnavailable(f"model server not reachable at {self.url} ({exc}). Is the Colab notebook still running?") from exc
