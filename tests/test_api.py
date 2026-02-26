from fastapi.testclient import TestClient

from app.api import app


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-key"}


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_auth_required() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/product-types")
    assert response.status_code == 401


def test_product_types_and_search() -> None:
    with TestClient(app) as client:
        response = client.get("/v1/product-types", headers=_headers())
        assert response.status_code == 200
        assert len(response.json()) >= 1

        payload = {
            "product_type_query": "USP reference standards",
            "limit": 5,
        }
        search_response = client.post("/v1/search/vendors", headers=_headers(), json=payload)
        assert search_response.status_code == 200
        body = search_response.json()
        assert body["normalized_query"]
        assert isinstance(body["data"], list)


def test_vendor_detail_roundtrip() -> None:
    with TestClient(app) as client:
        search_response = client.post(
            "/v1/search/vendors",
            headers=_headers(),
            json={"product_type_query": "analytical reagents", "limit": 1},
        )
        assert search_response.status_code == 200

        data = search_response.json()["data"]
        assert data

        vendor_id = data[0]["id"]
        detail = client.get(f"/v1/vendors/{vendor_id}", headers=_headers())
        assert detail.status_code == 200
        assert detail.json()["vendor"]["id"] == vendor_id
