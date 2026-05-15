import asyncio
import json
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from debate_engine import research_debate

results_dir = Path(__file__).parent / "results"

_FOLDER_PATTERN = re.compile(r"^\d{8}-.+")
_FOLDER_STRICT = re.compile(r"^\d{8}-[a-z0-9-]+$")

app = FastAPI()

# In-memory job store: job_id -> asyncio.Queue
# If the client disconnects before /api/stream is opened, run_pipeline() may
# still push events until it finishes; the jobs entry is only removed in
# event_generator's finally block (which never runs if the stream was never consumed).
jobs: dict[str, asyncio.Queue] = {}


class ChatRequest(BaseModel):
    topic: str
    folder: str | None = None


@app.post("/api/chat")
async def start_chat(req: ChatRequest):
    job_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    jobs[job_id] = queue

    # Load existing result.md as context if continuing a session
    context = ""
    save_folder = None
    if req.folder and _FOLDER_STRICT.match(req.folder):
        result_file = results_dir / req.folder / "result.md"
        if result_file.exists():
            context = result_file.read_text(encoding="utf-8")
            save_folder = req.folder

    async def on_event(event: dict):
        await queue.put(event)

    async def run_pipeline():
        try:
            await research_debate(req.topic, on_event=on_event, context=context, save_folder=save_folder)
        except Exception as e:
            await queue.put({"type": "error", "message": str(e)})
        finally:
            await queue.put(None)  # sentinel — signals stream to close

    asyncio.create_task(run_pipeline())
    return {"job_id": job_id}


@app.get("/api/stream/{job_id}")
async def stream(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    queue = jobs[job_id]

    async def event_generator():
        try:
            while True:
                item = await queue.get()
                if item is None:  # sentinel — pipeline finished
                    yield "data: " + json.dumps({"type": "done"}) + "\n\n"
                    break
                yield "data: " + json.dumps(item) + "\n\n"
        finally:
            jobs.pop(job_id, None)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _parse_folder_date(folder_name: str):
    """Return a sortable tuple (year, month, day) from a ddmmyyyy-slug folder name."""
    prefix = folder_name[:8]
    day = int(prefix[0:2])
    month = int(prefix[2:4])
    year = int(prefix[4:8])
    return (year, month, day)


@app.get("/api/sessions")
async def list_sessions():
    if not results_dir.exists():
        return []

    sessions = []
    for folder in results_dir.iterdir():
        if not folder.is_dir():
            continue
        name = folder.name
        if not _FOLDER_PATTERN.match(name):
            continue
        if not (folder / "result.md").exists():
            continue
        prefix = name[:8]
        slug = name[9:]  # everything after the first dash
        title = slug.replace("-", " ")
        date = f"{prefix[0:2]}/{prefix[2:4]}/{prefix[4:8]}"
        sessions.append({
            "folder": name,
            "title": title,
            "date": date,
            "_sort_key": _parse_folder_date(name),
        })

    sessions.sort(key=lambda s: s["_sort_key"], reverse=True)
    sessions = sessions[:50]

    # Remove internal sort key before returning
    for s in sessions:
        del s["_sort_key"]

    return sessions


@app.get("/api/sessions/{folder}")
async def get_session(folder: str):
    if not _FOLDER_STRICT.match(folder):
        raise HTTPException(status_code=400, detail="Invalid folder name")

    result_file = results_dir / folder / "result.md"
    if not result_file.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    return {"content": result_file.read_text(encoding="utf-8")}


# Serve static files — must come after API routes so /api/* is matched first
static_dir = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
