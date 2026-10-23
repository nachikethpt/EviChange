"""GPTClient: the ungated GPT comparison arm (D16). Same interface as VLMClient, so the
ungated report code (agents/ungated.py) treats Qwen and GPT identically.

Modes, picked from the environment (EVICHANGE_GPT):
  off     (default) every call raises VLMUnavailable. An OPENAI_API_KEY alone never turns
          this on: sending chips to OpenAI costs money and moves imagery off our own GPU,
          so it has to be asked for explicitly.
  replay  Answers come from a JSON file (GPT_REPLAY_FILE), keyed like VLMClient's replay file,
          for tests and for re-scoring recorded runs without calling the API.
  http    OpenAI Chat Completions with image inputs. Needs EVICHANGE_GPT=http, OPENAI_API_KEY
          and OPENAI_MODEL (no default: the reported model name must be a deliberate choice).
"""
from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .vlm_client import VLMUnavailable

API_URL = "https://api.openai.com/v1/chat/completions"


class GPTClient:
    def __init__(self, mode: str | None = None, api_key: str | None = None, model: str | None = None,
                 replay_file: str | None = None, timeout_s: float = 180):
        self.mode = mode or os.environ.get("EVICHANGE_GPT") or "off"
        self.api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self.model = model if model is not None else os.environ.get("OPENAI_MODEL", "")
        self.replay_file = replay_file or os.environ.get("GPT_REPLAY_FILE", "")
        self.timeout_s = timeout_s
        self._replay: dict | None = None

    def status(self) -> dict:
        """{"available": bool, "mode": str, "model": str | None, "detail": str}. Never raises, never calls the API."""
        if self.mode == "replay":
            ok = bool(self.replay_file) and Path(self.replay_file).exists()
            return {"available": ok, "mode": "replay", "model": "replay",
                    "detail": f"replaying {self.replay_file}" if ok else "GPT_REPLAY_FILE not found"}
        if self.mode == "http":
            missing = [name for name, value in (("OPENAI_API_KEY", self.api_key), ("OPENAI_MODEL", self.model)) if not value]
            if missing:
                return {"available": False, "mode": "http", "model": self.model or None,
                        "detail": f"EVICHANGE_GPT=http but {' and '.join(missing)} not set."}
            return {"available": True, "mode": "http", "model": self.model, "detail": API_URL}
        return {"available": False, "mode": "off", "model": None,
                "detail": "Ungated GPT is off: set EVICHANGE_GPT=http, OPENAI_API_KEY and OPENAI_MODEL to run it (D16)."}

    def generate(self, prompt: str, images: list[bytes] = (), max_new_tokens: int = 800, replay_key: str | None = None) -> dict:
        """{"text": str, "model": str}. Raises VLMUnavailable when there is no usable model."""
        status = self.status()
        if not status["available"]:
            raise VLMUnavailable(status["detail"])
        if self.mode == "replay":
            if self._replay is None:
                self._replay = json.loads(Path(self.replay_file).read_text(encoding="utf-8"))
            if replay_key not in self._replay:
                raise VLMUnavailable(f"no recorded answer for {replay_key!r}")
            return {"text": self._replay[replay_key], "model": "replay"}
        content = [{"type": "text", "text": prompt}] + [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(i).decode("ascii")}}
            for i in images]
        payload = {"model": self.model, "messages": [{"role": "user", "content": content}],
                   "max_completion_tokens": max_new_tokens}
        body = self._post(payload)
        try:
            text = body["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise VLMUnavailable(f"unexpected OpenAI response: {str(body)[:200]}") from exc
        return {"text": text, "model": body.get("model") or self.model}

    def _post(self, payload: dict) -> dict:
        req = urllib.request.Request(API_URL, data=json.dumps(payload).encode(), method="POST",
                                     headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:200]
            if exc.code in (401, 403):
                raise VLMUnavailable("OpenAI rejected OPENAI_API_KEY") from exc
            raise VLMUnavailable(f"OpenAI error {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise VLMUnavailable(f"OpenAI not reachable ({exc})") from exc
