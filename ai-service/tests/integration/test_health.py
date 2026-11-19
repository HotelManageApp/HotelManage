import httpx


async def test_health(client: httpx.AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "test-sha", "llm_provider": "fake"}
    assert "X-Request-ID" in response.headers
