from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.db import ready

app = FastAPI(title="Georgia WindCast", version="0.1.0")


@app.get("/health/live")
def live():
    return {"status": "ok"}


@app.get("/health/ready")
def readiness():
    try:
        ready()
    except Exception:
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return {"status": "ok"}


@app.get("/api/status")
def status():
    return {
        "generation": {"status": "unavailable", "value_mw": None},
        "weather": {"status": "unavailable", "sites": []},
        "reason": "Sources have not been integrated or verified.",
    }
