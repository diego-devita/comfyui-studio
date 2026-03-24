"""ComfyUI Studio — HTML page serve routes."""

from fastapi import HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse

from config import app
from catalogs import _www


# ── Root & page routes ───────────────────────────────────────────────────────


@app.get("/")
async def root():
    return RedirectResponse("/home", status_code=302)


@app.get("/home", response_class=HTMLResponse)
async def serve_home():
    return HTMLResponse(_www("home.html").read_text())


@app.get("/admin/models", response_class=HTMLResponse)
async def serve_models():
    return HTMLResponse(_www("models.html").read_text())


@app.get("/admin/loras", response_class=HTMLResponse)
async def serve_loras():
    return HTMLResponse(_www("loras.html").read_text())


@app.get("/admin/workflows", response_class=HTMLResponse)
async def serve_workflows_page():
    return HTMLResponse(_www("workflows.html").read_text())


@app.get("/admin/nodes", response_class=HTMLResponse)
async def serve_nodes_page():
    return HTMLResponse(_www("nodes.html").read_text())


@app.get("/admin/queue", response_class=HTMLResponse)
async def serve_queue_page():
    return HTMLResponse(_www("queue.html").read_text())


@app.get("/admin/history", response_class=HTMLResponse)
async def serve_history_page():
    return HTMLResponse(_www("history.html").read_text())


@app.get("/admin/assets", response_class=HTMLResponse)
async def serve_assets_page():
    return HTMLResponse(_www("assets.html").read_text())


@app.get("/admin/settings", response_class=HTMLResponse)
async def serve_settings_page():
    return HTMLResponse(_www("settings.html").read_text())


@app.get("/admin/llm", response_class=HTMLResponse)
async def serve_llm_page():
    return HTMLResponse(_www("llm.html").read_text())


@app.get("/run/{workflow_id}", response_class=HTMLResponse)
async def serve_runner(workflow_id: str):
    return HTMLResponse(_www("runner.html").read_text())


@app.get("/static/{path:path}")
async def serve_static(path: str):
    p = _www(path)
    if not p.exists():
        raise HTTPException(404)
    content = p.read_text()
    if path.endswith(".css"):
        media = "text/css"
    elif path.endswith(".js"):
        media = "application/javascript"
    else:
        media = "text/plain"
    return HTMLResponse(content, media_type=media)
