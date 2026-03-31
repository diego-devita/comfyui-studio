"""ComfyUI Studio — Pipeline engine.

Pipelines are scripted sequences of LLM calls + job submissions.
Each pipeline is a Python module in this directory with a PIPELINE
descriptor dict and an async run() function.
"""

import asyncio
import importlib
import json
import os
import re
import time
import uuid
from pathlib import Path

import httpx

from config import DEV_MODE


# ── Pipeline registry ────────────────────────────────────────────────────────

_pipelines: dict[str, dict] = {}  # id → module


def _discover():
    """Import all pipeline modules in this directory."""
    pkg_dir = Path(__file__).parent
    for f in pkg_dir.glob("*.py"):
        if f.name.startswith("_"):
            continue
        mod_name = f"pipelines.{f.stem}"
        try:
            mod = importlib.import_module(mod_name)
            if hasattr(mod, "PIPELINE") and hasattr(mod, "run"):
                _pipelines[mod.PIPELINE["id"]] = mod
        except Exception as e:
            print(f"[pipelines] Failed to load {mod_name}: {e}")


def list_pipelines() -> list[dict]:
    if not _pipelines:
        _discover()
    return [m.PIPELINE for m in _pipelines.values()]


def get_pipeline(pipeline_id: str):
    if not _pipelines:
        _discover()
    return _pipelines.get(pipeline_id)


# ── Run context ──────────────────────────────────────────────────────────────

class PipelineContext:
    """Provides utilities to pipeline scripts: LLM chat, job submission, logging."""

    def __init__(self, run_id: str, pipeline_id: str, inputs: dict, resolved_instances: dict):
        self.run_id = run_id
        self.pipeline_id = pipeline_id
        self.inputs = inputs
        self.resolved_instances = resolved_instances  # requirement_id → instance info
        self.steps = []  # [{name, started_at, finished_at, output, error}]
        self.log_lines = []  # [(timestamp, message)]
        self.current_step = None
        self.status = "running"  # running, completed, failed
        self.error = None
        self.result = None
        self._started_at = time.time()

    def set_step(self, name: str):
        if self.current_step:
            self.current_step["finished_at"] = time.time()
        step = {"name": name, "started_at": time.time(), "finished_at": None, "output": None}
        self.steps.append(step)
        self.current_step = step
        self.log(f"▶ {name}")

    def log(self, message: str):
        self.log_lines.append((time.time(), message))
        # Persist to DB
        try:
            import llm_db as db
            elapsed = time.time() - self._started_at
            db.append_pipeline_log(self.run_id, f"[{elapsed:.1f}s] {message}")
        except Exception:
            pass

    async def llm_chat(self, preset_id: str, message: str, requirement_id: str, image_id: str = None) -> str:
        """Send a message to an LLM instance via the conversation API. Returns the response text."""
        inst = self.resolved_instances.get(requirement_id)
        if not inst:
            raise RuntimeError(f"No resolved instance for requirement '{requirement_id}'")

        from llm_server import _get_instance_port
        port = _get_instance_port(inst["instance_id"])
        if not port:
            raise RuntimeError(f"Instance '{inst['instance_id']}' port not found")

        # Build messages with system prompt from preset
        import llm_db as db
        from llm_server import _load_llm_config

        llm_messages = []
        preset = db.get_preset(preset_id) if preset_id else None
        if preset and preset.get("system_prompt"):
            llm_messages.append({"role": "system", "content": preset["system_prompt"]})

        # Build user content (text or multimodal)
        if image_id:
            import base64
            from config import LLM_IMAGES_DIR
            img_path = LLM_IMAGES_DIR / image_id
            if img_path.exists():
                b64 = base64.b64encode(img_path.read_bytes()).decode("ascii")
                user_content = [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    {"type": "text", "text": message},
                ]
            else:
                user_content = message
        else:
            user_content = message

        llm_messages.append({"role": "user", "content": user_content})

        config = _load_llm_config()
        temp = preset.get("temperature", 0.7) if preset else config.get("temp", 0.7)

        payload = {
            "messages": llm_messages,
            "temperature": temp,
            "stream": False,
        }

        if DEV_MODE:
            import random
            await asyncio.sleep(1)
            return f"[DEV] Pipeline stub response for preset={preset_id}, message={message[:50]}..."

        async with httpx.AsyncClient(timeout=300) as client:
            r = await client.post(f"http://127.0.0.1:{port}/v1/chat/completions", json=payload)
            if r.status_code != 200:
                raise RuntimeError(f"LLM returned {r.status_code}: {r.text[:200]}")
            data = r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return content

    async def submit_job(self, workflow_id: str, params: dict, image_id: str = None) -> str:
        """Submit a job to the runner. Returns job/prompt ID."""
        self.log(f"Submitting job to workflow {workflow_id}...")

        if DEV_MODE:
            fake_id = uuid.uuid4().hex[:8]
            self.log(f"[DEV] Job stub: {fake_id}")
            return fake_id

        # Register input image via centralized asset manager
        from config import LLM_IMAGES_DIR
        from input_assets import register_input_async

        input_image_name = None
        if image_id:
            src = LLM_IMAGES_DIR / image_id
            if src.exists():
                file_bytes = src.read_bytes()
                input_image_name = await register_input_async(file_bytes, image_id, source="pipeline")

        if input_image_name:
            params["_existing_input_image"] = input_image_name

        # Use API key from env (set by events.py at boot from DB settings)
        api_key = os.environ.get("API_KEY", "")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(
                f"http://127.0.0.1:8000/api/run/{workflow_id}/execute",
                data={"params": json.dumps(params)},
                headers={"X-API-Key": api_key},
            )
            if r.status_code != 200:
                raise RuntimeError(f"Job submission failed: {r.status_code} {r.text[:200]}")
            data = r.json()
            return data.get("prompt_id", data.get("id", "unknown"))

    def to_dict(self) -> dict:
        elapsed = time.time() - self._started_at
        steps_out = []
        for s in self.steps:
            duration = (s["finished_at"] or time.time()) - s["started_at"]
            steps_out.append({"name": s["name"], "duration": round(duration, 1), "output": s.get("output")})
        return {
            "run_id": self.run_id,
            "pipeline_id": self.pipeline_id,
            "status": self.status,
            "error": self.error,
            "elapsed": round(elapsed, 1),
            "steps": steps_out,
            "log": [{"t": round(t - self._started_at, 1), "msg": m} for t, m in self.log_lines],
            "result": self.result,
        }


# ── Run manager ──────────────────────────────────────────────────────────────

_runs: dict[str, PipelineContext] = {}  # run_id → context


def check_requirements(pipeline_mod) -> list[dict]:
    """Check if all required models are running. Returns list of {requirement, status, instance, model_present}."""
    from llm_server import _get_running_instances
    from config import LLM_MODELS_DIR

    instances = _get_running_instances()
    results = []
    for req in pipeline_mod.PIPELINE.get("requires", []):
        # Support both single "model" and multi "models" requirements
        model_list = req.get("models", [req["model"]] if req.get("model") else [])
        found = None
        found_model = None
        for model_file in model_list:
            for inst in instances:
                if inst["model"] == model_file and inst.get("alive"):
                    ctx = inst.get("config", {}).get("ctx_size", 0)
                    if ctx >= req.get("min_ctx", 0):
                        found = inst
                        found_model = model_file
                        break
            if found:
                break
        # Check which models are present on disk
        models_status = []
        for model_file in model_list:
            models_status.append({
                "model": model_file,
                "present": (LLM_MODELS_DIR / model_file).exists(),
            })
        results.append({
            "requirement": req,
            "satisfied": found is not None,
            "active_model": found_model,
            "models_status": models_status,
            "instance": found,
        })
    return results


async def start_run(pipeline_id: str, inputs: dict) -> PipelineContext:
    """Start a pipeline run in the background. Returns the context."""
    mod = get_pipeline(pipeline_id)
    if not mod:
        raise ValueError(f"Pipeline '{pipeline_id}' not found")

    # Check requirements
    req_status = check_requirements(mod)
    unmet = [r for r in req_status if not r["satisfied"]]
    if unmet:
        names = [r["requirement"]["label"] for r in unmet]
        raise RuntimeError(f"Requirements not met: {', '.join(names)}")

    resolved = {r["requirement"]["id"]: r["instance"] for r in req_status}

    run_id = uuid.uuid4().hex[:12]
    ctx = PipelineContext(run_id, pipeline_id, inputs, resolved)
    _runs[run_id] = ctx

    # Persist to DB
    import llm_db as db
    db.create_pipeline_run(run_id, pipeline_id, image_id=inputs.get("image"), inputs=inputs)

    async def _execute():
        try:
            result = await mod.run(inputs, ctx)
            if ctx.current_step:
                ctx.current_step["finished_at"] = time.time()
            ctx.status = "completed"
            ctx.result = result
            ctx.log(f"✓ Pipeline completed")
            db.finish_pipeline_run(run_id, "completed", result=result)
        except Exception as e:
            ctx.status = "failed"
            ctx.error = str(e)
            ctx.log(f"✗ Error: {e}")
            db.finish_pipeline_run(run_id, "failed", error=str(e))

    asyncio.create_task(_execute())
    return ctx


def get_run(run_id: str) -> PipelineContext | None:
    return _runs.get(run_id)


def list_runs() -> list[dict]:
    return [ctx.to_dict() for ctx in _runs.values()]
