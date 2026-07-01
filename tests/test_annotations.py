"""Annotation and reporting tests: round-trips, validation, and authorization."""

from tests.conftest import admin_headers, auth_headers


def _sample(**overrides):
    payload = {
        "project_id": 1,
        "llm_output": "The capital of France is Paris.",
        "score": 5.0,
        "label": "correct",
    }
    payload.update(overrides)
    return payload


def test_create_requires_auth(client):
    assert client.post("/annotations/", json=_sample()).status_code == 401


def test_create_and_read_round_trip(client):
    headers = auth_headers(client)
    created = client.post("/annotations/", json=_sample(notes="Accurate."), headers=headers)
    assert created.status_code == 201
    body = created.json()
    assert body["label"] == "correct"
    assert body["notes"] == "Accurate."
    assert body["user_id"] >= 1

    fetched = client.get(f"/annotations/{body['id']}", headers=headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == body["id"]


def test_score_out_of_range_is_rejected(client):
    headers = auth_headers(client)
    assert client.post("/annotations/", json=_sample(score=9.0), headers=headers).status_code == 422


def test_unknown_label_is_rejected(client):
    headers = auth_headers(client)
    resp = client.post("/annotations/", json=_sample(label="banana"), headers=headers)
    assert resp.status_code == 422


def test_missing_annotation_returns_404(client):
    headers = auth_headers(client)
    assert client.get("/annotations/999", headers=headers).status_code == 404


def test_annotations_are_scoped_to_their_owner(client):
    alice = auth_headers(client, email="alice@example.com")
    bob = auth_headers(client, email="bob@example.com")

    created = client.post("/annotations/", json=_sample(), headers=alice).json()

    # Bob cannot see Alice's annotation (404, not 403 — no existence leak).
    assert client.get(f"/annotations/{created['id']}", headers=bob).status_code == 404
    # ...nor does it appear in his list, while it does appear in hers.
    assert client.get("/annotations/", headers=bob).json() == []
    assert len(client.get("/annotations/", headers=alice).json()) == 1


def test_list_filters_by_label(client):
    headers = auth_headers(client)
    client.post("/annotations/", json=_sample(label="correct"), headers=headers)
    client.post("/annotations/", json=_sample(label="hallucination", score=1.0), headers=headers)

    only_hallucinations = client.get("/annotations/?label=hallucination", headers=headers).json()
    assert len(only_hallucinations) == 1
    assert only_hallucinations[0]["label"] == "hallucination"


def test_admin_sees_all_annotations(client):
    annotator = auth_headers(client, email="ann@example.com")
    admin = admin_headers(client)

    client.post("/annotations/", json=_sample(), headers=annotator)

    assert len(client.get("/annotations/", headers=admin).json()) == 1


def test_owner_can_delete_own_annotation(client):
    headers = auth_headers(client)
    created = client.post("/annotations/", json=_sample(), headers=headers).json()

    assert client.delete(f"/annotations/{created['id']}", headers=headers).status_code == 204
    # The row is actually gone, not just hidden.
    assert client.get(f"/annotations/{created['id']}", headers=headers).status_code == 404


def test_non_owner_cannot_delete(client):
    alice = auth_headers(client, email="alice2@example.com")
    bob = auth_headers(client, email="bob2@example.com")
    created = client.post("/annotations/", json=_sample(), headers=alice).json()

    # Bob is scoped out (404, no existence leak) and the row survives for Alice.
    assert client.delete(f"/annotations/{created['id']}", headers=bob).status_code == 404
    assert client.get(f"/annotations/{created['id']}", headers=alice).status_code == 200


def test_delete_missing_annotation_returns_404(client):
    headers = auth_headers(client)
    assert client.delete("/annotations/999", headers=headers).status_code == 404


def test_admin_can_delete_any_annotation(client):
    annotator = auth_headers(client, email="ann3@example.com")
    admin = admin_headers(client)
    created = client.post("/annotations/", json=_sample(), headers=annotator).json()

    assert client.delete(f"/annotations/{created['id']}", headers=admin).status_code == 204


def test_summary_report_aggregates_counts_and_average(client):
    headers = auth_headers(client)
    client.post("/annotations/", json=_sample(label="correct", score=5.0), headers=headers)
    client.post("/annotations/", json=_sample(label="hallucination", score=1.0), headers=headers)

    body = client.get("/reports/summary", headers=headers).json()
    assert body["total_annotations"] == 2
    assert body["by_label"]["correct"] == 1
    assert body["by_label"]["hallucination"] == 1
    assert body["by_label"]["partial"] == 0
    assert body["average_score"] == 3.0
    assert body["reviewed_by"] == "annotator@example.com"
