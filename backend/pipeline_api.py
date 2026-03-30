"""ComfyUI Studio — Pipeline API."""

import json

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import JSONResponse, StreamingResponse

from pipelines import list_pipelines, get_pipeline, check_requirements, start_run, get_run, list_runs

router = APIRouter()


@router.get("/api/admin/pipelines")
async def pipelines_list():
    """List all available pipelines with their descriptors."""
    return JSONResponse(list_pipelines())


@router.get("/api/admin/pipelines/runs")
async def pipeline_runs_list():
    """List all pipeline runs (in-memory active + DB history)."""
    return JSONResponse(list_runs())


@router.get("/api/admin/pipelines/history")
async def pipeline_history():
    """List persisted pipeline run history from DB."""
    import llm_db as db
    return JSONResponse(db.list_pipeline_runs(limit=50))


@router.get("/api/admin/pipelines/history/{run_id}")
async def pipeline_history_detail(run_id: str):
    """Get a persisted pipeline run with full log."""
    import llm_db as db
    run = db.get_pipeline_run(run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    return JSONResponse(run)


@router.get("/api/admin/pipelines/runs/{run_id}")
async def pipeline_run_status(run_id: str):
    """Get the current status of a pipeline run."""
    ctx = get_run(run_id)
    if not ctx:
        raise HTTPException(404, "Run not found")
    return JSONResponse(ctx.to_dict())


@router.get("/api/admin/pipelines/{pipeline_id}")
async def pipeline_detail(pipeline_id: str):
    """Get a pipeline descriptor + check requirements status."""
    mod = get_pipeline(pipeline_id)
    if not mod:
        raise HTTPException(404, "Pipeline not found")
    desc = dict(mod.PIPELINE)
    desc["requirements_status"] = check_requirements(mod)
    return JSONResponse(desc)


@router.post("/api/admin/pipelines/{pipeline_id}/run")
async def pipeline_run(pipeline_id: str, request: Request):
    """Start a pipeline run. Body: {inputs: {image, description, scenes, ...}}"""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    inputs = body.get("inputs", {})

    try:
        ctx = await start_run(pipeline_id, inputs)
        return JSONResponse({"run_id": ctx.run_id, "status": "started"})
    except RuntimeError as e:
        raise HTTPException(412, str(e))
    except ValueError as e:
        raise HTTPException(404, str(e))
