def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "db": True, "mqtt": "disabled"}


def test_planned_routes_exist_and_return_501(client):
    # 수꽝 관리자 확인(작업 9)은 나중에, 떵개(수빈) API는 수빈 앱과 합칠 때까지 501 자리만 둔다
    for method, path in [
        ("get", "/admin/reviews"), ("get", "/admin/reviews/r1/crop"),
        ("post", "/admin/reviews/r1/resolve"),
        ("get", "/qr/QR-B2-ENT1"), ("get", "/route?from=QR-B2-ENT1&to=B2-A-03"), ("get", "/map?floor=B2"),
    ]:
        r = getattr(client, method)(path)
        assert r.status_code == 501, (method, path, r.status_code)
        assert r.json()["error"]["code"] == "NOT_IMPLEMENTED"


def test_unknown_path_uses_error_format(client):
    r = client.get("/nope")
    assert r.status_code == 404 and "error" in r.json()


def test_openapi_lists_both_owners(client):
    tags = {t for p in client.get("/openapi.json").json()["paths"].values() for op in p.values() for t in op.get("tags", [])}
    assert any("수꽝" in t for t in tags) and any("떵개" in t for t in tags)
