def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": True, "mqtt": "disabled"}


def test_admin_routes_require_authentication(client):
    # 수꽝 관리자 확인(작업 9)은 나중에, 떵개(수빈) API는 수빈 앱과 합칠 때까지 501 자리만 둔다
    for method, path in [
        ("get", "/admin/reviews"), ("post", "/admin/reviews/r1/resolve"),
    ]:
        r = getattr(client, method)(path)
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.json()["error"]["code"] == "UNAUTHORIZED"


def test_map_routes_report_missing_data_instead_of_stub(client):
    for path in ['/qr/QR-B2-ENT1', '/route?from=QR-B2-ENT1&to=B2-A-03', '/map?floor=B2']:
        response = client.get(path)
        assert response.status_code == 404
        assert response.json()['error']['code'] == 'NOT_FOUND'


def test_unknown_path_uses_error_format(client):
    r = client.get("/nope")
    assert r.status_code == 404 and "error" in r.json()


def test_openapi_lists_both_owners(client):
    tags = {t for p in client.get("/openapi.json").json()["paths"].values() for op in p.values() for t in op.get("tags", [])}
    assert any("수꽝" in t for t in tags) and any("떵개" in t for t in tags)
