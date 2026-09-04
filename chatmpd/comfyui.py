"""Local ComfyUI API transport."""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.parse import urlparse


JsonObject = dict[str, Any]
RequestJson = Callable[[str, str, JsonObject | None], JsonObject]


@dataclass(frozen=True)
class ComfyUIResult:
    status: str
    job_id: str
    outputs: Mapping[str, Any]


class ComfyUIClient:
    """Small native API client restricted to local loopback by default."""

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:8188",
        *,
        request_json: RequestJson | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("ComfyUI endpoint must use HTTP or HTTPS.")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("ComfyUI endpoint must be a loopback address by default.")
        self.endpoint = endpoint.rstrip("/")
        self._request_json = request_json or self._http_json
        self._sleep = sleep

    def _http_json(
        self,
        method: str,
        path: str,
        payload: JsonObject | None = None,
    ) -> JsonObject:
        data = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.endpoint}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        if not body:
            return {}
        decoded = json.loads(body.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise RuntimeError("ComfyUI returned an unexpected response shape.")
        return decoded

    def submit(self, workflow: Mapping[str, Any]) -> str:
        response = self._request_json(
            "POST", "/prompt", {"prompt": dict(workflow)}
        )
        job_id = str(response.get("prompt_id", "")).strip()
        if not job_id:
            raise RuntimeError("ComfyUI did not return a prompt_id.")
        return job_id

    def history(self, job_id: str) -> JsonObject:
        return self._request_json("GET", f"/history/{job_id}", None)

    def wait(
        self,
        job_id: str,
        *,
        poll_interval: float,
        timeout: float,
    ) -> ComfyUIResult:
        deadline = time.monotonic() + timeout
        while True:
            history = self.history(job_id)
            entry = history.get(job_id)
            if isinstance(entry, dict):
                status = entry.get("status") or {}
                status_text = str(status.get("status_str", "success")).casefold()
                completed = bool(status.get("completed")) or "outputs" in entry
                if completed and status_text not in {"success", "completed"}:
                    raise RuntimeError(
                        f"ComfyUI job {job_id} finished with status {status_text}."
                    )
                if completed:
                    outputs = entry.get("outputs") or {}
                    if not isinstance(outputs, dict):
                        raise RuntimeError("ComfyUI returned invalid output metadata.")
                    return ComfyUIResult("completed", job_id, outputs)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for ComfyUI job {job_id}.")
            self._sleep(poll_interval)


class ComfyUIBackend:
    """Translate a normalized job plan into an API workflow and execute it."""

    def __init__(
        self,
        client: ComfyUIClient,
        *,
        workflow_builder: Callable[[Any], Mapping[str, Any]],
        poll_interval: float = 0.5,
        completion_timeout: float = 3600,
    ) -> None:
        if poll_interval < 0 or completion_timeout <= 0:
            raise ValueError("Invalid ComfyUI polling configuration.")
        self.client = client
        self.workflow_builder = workflow_builder
        self.poll_interval = poll_interval
        self.completion_timeout = completion_timeout

    def generate(self, plan: Any) -> ComfyUIResult:
        workflow = self.workflow_builder(plan)
        if not isinstance(workflow, Mapping) or not workflow:
            raise ValueError("ComfyUI workflow builder returned no executable workflow.")
        job_id = self.client.submit(workflow)
        return self.client.wait(
            job_id,
            poll_interval=self.poll_interval,
            timeout=self.completion_timeout,
        )
