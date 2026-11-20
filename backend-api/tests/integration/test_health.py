import httpx

from app.main import create_app
from tests.conftest import make_settings


async def test_health_ok_with_database(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok", "version": "test-sha"}
    assert "X-Request-ID" in response.headers


async def test_health_503_when_database_unreachable() -> None:
    settings = make_settings(
        database_url="postgresql+asyncpg://hotel:wrong@127.0.0.1:1/nowhere",
        db_health_timeout_seconds=2.0,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
    assert response.status_code == 503
    assert response.json()["db"] == "error"
    assert response.json()["status"] == "degraded"
