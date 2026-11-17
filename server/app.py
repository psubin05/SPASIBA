"""Map/route APIs conforming to docs/server_interface.md, plus a local simulator."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from server.map_store import MapStore
from server.route import route

ROOT = Path(__file__).resolve().parents[1]


def create_app(map_path=None, *, demo_db=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.maps = MapStore(map_path or ROOT / 'map/b2.json')
        if demo_db is not None:
            from server.demo_parking import DemoParking
            app.state.parking = DemoParking(demo_db, app.state.maps)
        yield

    app = FastAPI(title='SPASIBA Map & Route', lifespan=lifespan)

    @app.middleware('http')
    async def fresh_responses(request, call_next):
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response
    if demo_db is not None:
        import sqlite3
        from server.demo_parking import DemoError, demo_router
        app.include_router(demo_router())

        @app.exception_handler(DemoError)
        async def demo_error(request, exc):
            return JSONResponse(status_code=exc.status, content={'error': {'code': exc.code, 'message': exc.message}})

        @app.exception_handler(sqlite3.OperationalError)
        async def storage_unavailable(request, exc):
            return JSONResponse(status_code=503, content={'error': {'code': 'STORAGE_UNAVAILABLE', 'message': '입차 저장소를 사용할 수 없습니다. 잠시 후 기록을 확인하고 다시 시도해주세요.'}})
    app.mount('/simulator/assets', StaticFiles(directory=ROOT / 'simulator'), name='simulator-assets')

    @app.get('/simulator/layout', include_in_schema=False)
    def simulator_layout(request: Request):
        store = request.app.state.maps
        if 'demo_layout' not in store.data:
            return error(404, 'NOT_FOUND', '시뮬레이터 배치 정보가 없습니다.')
        return {'sample': store.data.get('sample', True),
                'demo_enabled': demo_db is not None,
                'qr_locations': list(store.qrs.values()),
                'layout': store.data['demo_layout']}

    def error(status, code, message):
        return JSONResponse(status_code=status, content={'error': {'code': code, 'message': message}})

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return error(422, 'INVALID_REQUEST', '필수 요청 값과 형식을 확인해주세요.')

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return error(exc.status_code, 'NOT_FOUND' if exc.status_code == 404 else 'HTTP_ERROR', str(exc.detail))

    @app.get('/health')
    def health():
        return {'status': 'ok', 'scope': 'map-route', 'mode': 'local-demo' if demo_db is not None else 'map-only'}

    @app.get('/qr/{location_id}')
    def qr(location_id: str, request: Request):
        item = request.app.state.maps.qrs.get(location_id)
        return item if item else error(404, 'NOT_FOUND', 'QR을 다시 스캔해주세요.')

    @app.get('/map')
    def get_map(request: Request, floor: str = Query(..., min_length=1)):
        store = request.app.state.maps
        if floor != store.data['floor']:
            return error(404, 'NOT_FOUND', '해당 층의 지도가 없습니다.')
        return store.public_map()

    @app.get('/route')
    def get_route(request: Request, origin: str = Query(..., alias='from', min_length=1),
                  destination: str = Query(..., alias='to', min_length=1)):
        store = request.app.state.maps
        try:
            return route(store.data, origin, destination, cache=(store.nodes, store.graph))
        except KeyError:
            return error(404, 'NOT_FOUND', '출발 QR 또는 도착 주차면을 찾을 수 없습니다.')
        except ValueError:
            return error(404, 'NO_ROUTE', '이동 가능한 경로가 없습니다.')

    @app.get('/simulator', include_in_schema=False)
    def simulator():
        return FileResponse(ROOT / 'simulator/index.html')

    return app


app = create_app()
