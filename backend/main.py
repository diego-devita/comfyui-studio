"""ComfyUI Studio — Entry Point"""
from config import app

# Initialize database
import db
db.init_db()

# Register middleware and auth
import auth

# Start event system
import events

# Register page routes
import pages

# Register API routers
from models_api import router as models_router
from llm_api import router as llm_router
from llm_chat_api import router as llm_chat_router
from workflows_api import router as workflows_router
from runner_api import router as runner_router
from system_api import router as system_router
from jobs_api import router as jobs_router
from loras_api import router as loras_router
from presets_api import router as presets_router
from civitai_api import router as civitai_router

app.include_router(models_router)
app.include_router(llm_router)
app.include_router(llm_chat_router)
app.include_router(workflows_router)
app.include_router(runner_router)
app.include_router(system_router)
app.include_router(jobs_router)
app.include_router(loras_router)
app.include_router(presets_router)
app.include_router(civitai_router)
