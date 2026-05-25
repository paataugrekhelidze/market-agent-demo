# agent_runner.py
from fastapi import FastAPI, HTTPException
from prefect.deployments import run_deployment
from pydantic import BaseModel
import httpx, os
from contextlib import asynccontextmanager

AGENT_CONCURRENCY_LIMIT = int(os.environ.get("AGENT_CONCURRENCY_LIMIT") or "3")
PIPELINE_QUEUE_TIMEOUT = int(os.environ.get("PIPELINE_QUEUE_TIMEOUT") or "60")
PREFECT_API_URL = os.environ.get("PREFECT_API_URL", "http://localhost:4200/api")
DEPLOYMENT_NAME = "resumable-pipeline/kubernetes-deployment"  # <flow-name>/<deployment-name>

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{PREFECT_API_URL}/v2/concurrency_limits/agent-pipeline")
        if resp.status_code == 404:
            await client.post(
                f"{PREFECT_API_URL}/v2/concurrency_limits/",
                json={"name": "agent-pipeline", "limit": AGENT_CONCURRENCY_LIMIT, "active": True},
            )
    yield

app = FastAPI(title="Market Agent API", lifespan=lifespan)

class RunRequest(BaseModel):
    intent: str
    max_tasks: int = 5

class RunResponse(BaseModel):
    result: str

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/run", response_model=RunResponse)
async def run_pipeline(req: RunRequest):
    flow_run = await run_deployment(
        name=DEPLOYMENT_NAME,
        parameters={"user_intent": req.intent, "max_tasks": req.max_tasks},
        timeout=PIPELINE_QUEUE_TIMEOUT,  # seconds to wait for a result;
    )
    if flow_run.state.is_failed():
        raise HTTPException(status_code=500, detail="Pipeline failed")
    # flow_run.state.result() fetches the persisted output
    result = await flow_run.state.result(fetch=True)
    return RunResponse(result=result)