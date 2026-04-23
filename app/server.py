import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from app.gemini_live import LiveVoiceBridge

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-live-preview")

app = FastAPI(title="Gemini Live Voice Bot")
app.mount("/web", StaticFiles(directory="web"), name="web")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse("web/index.html")


@app.get("/health")
async def health() -> JSONResponse:
    return JSONResponse({"ok": True, "model": MODEL})


@app.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    await websocket.accept()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        await websocket.send_json(
            {"type": "error", "message": "GEMINI_API_KEY is not set on server."}
        )
        await websocket.close(code=1011)
        return

    bridge = LiveVoiceBridge(websocket=websocket, api_key=api_key, model=MODEL)
    try:
        await bridge.run()
    except WebSocketDisconnect:
        logger.info("Browser disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Live session failed: %s", exc)
        await websocket.send_json({"type": "error", "message": str(exc)})
        await websocket.close(code=1011)


def run() -> None:
    uvicorn.run("app.server:app", host=HOST, port=PORT, reload=True)

