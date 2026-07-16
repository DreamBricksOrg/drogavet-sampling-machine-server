def test_novas_rotas_registradas():
    from domains.users.routes import session_router

    paths = {route.path for route in session_router.routes}
    assert "/api/sample/start" in paths
    assert "/api/sample/session/pickup" in paths
    assert "/api/sample/thanks" in paths
