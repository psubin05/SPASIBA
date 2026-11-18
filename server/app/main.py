"""SPASIBA Cloud API 서버 (명세서 v1.2: 단일 배포 단위).

실행:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings
from .db import Database
from .mqtt_listener import MqttListener
from .parking import ParkingError
from .routers import parking, stubs, maps, simulator
from .map_service import seed_sample, ROOT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    database = Database(settings.database_url)
    mqtt = MqttListener(settings, database)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        database.create_all()
        if settings.seed_sample_map:
            seed_sample(database)
        mqtt.start()
        try:
            yield
        finally:
            mqtt.stop()
            database.engine.dispose()

    app = FastAPI(title="SPASIBA Cloud API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.db = database
    app.state.mqtt = mqtt
    app.mount('/simulator/assets', StaticFiles(directory=ROOT / 'simulator'), name='simulator-assets')

    @app.middleware('http')
    async def no_stale_response(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response

    @app.get("/health", tags=["공동"])
    def health():
        db_ok = database.ping()
        mqtt_state = "disabled" if not settings.mqtt_enabled else ("connected" if mqtt.connected else "disconnected")
        return {"status": "ok" if db_ok else "degraded", "db": db_ok, "mqtt": mqtt_state}

    @app.exception_handler(StarletteHTTPException)
    async def error_format(request, exc: StarletteHTTPException):
        # 오류 응답 형식 통일: {"error": {"code", "message"}} (인터페이스 문서 3장)
        if isinstance(exc.detail, dict) and "error" in exc.detail:
            body = exc.detail
        else:
            body = {"error": {"code": str(exc.status_code), "message": str(exc.detail)}}
        return JSONResponse(status_code=exc.status_code, content=body)

    @app.exception_handler(ParkingError)
    async def parking_error(request, exc: ParkingError):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc: RequestValidationError):
        fields = sorted({".".join(str(x) for x in e.get("loc", ())[1:]) for e in exc.errors()})
        return JSONResponse(status_code=422, content={"error": {
            "code": "INVALID_REQUEST", "message": "요청 값을 확인해 주세요: " + ", ".join(f for f in fields if f)}})

    app.include_router(parking.router)
    app.include_router(stubs.admin)
    app.include_router(maps.router)
    app.include_router(simulator.router)
    return app


app = create_app()
