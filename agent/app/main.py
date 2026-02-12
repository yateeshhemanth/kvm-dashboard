import threading

from fastapi import FastAPI

from .config import load_config
from .routes import create_router
from .services import heartbeat_loop
from .state import AgentState

CONFIG = load_config()
STATE = AgentState()
STOP_EVENT = threading.Event()

app = FastAPI(title="KVM Host Agent API", version="0.5.0")
app.include_router(create_router(CONFIG, STATE))


@app.on_event("startup")
def startup() -> None:
    threading.Thread(target=heartbeat_loop, args=(CONFIG, STATE, STOP_EVENT), daemon=True).start()


@app.on_event("shutdown")
def shutdown() -> None:
    STOP_EVENT.set()
