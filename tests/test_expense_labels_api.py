"""Contratti API della correzione manuale del raggruppamento voci di spesa.

Copre `/api/expense-labels/*` e lo switch `group=` di `/api/analytics/top-merchants`.
Verifica in particolare due invarianti che non sono dettagli implementativi:
- il cluster di un altro utente non è raggiungibile (ownership esplicita, non solo RLS
  — su SQLite la RLS è un no-op, quindi è l'unica difesa attiva nei test);
- nessun testo scritto dall'utente finisce nei log o nei messaggi d'errore.
"""

import logging
from datetime import date
from decimal import Decimal

import pytest


pytestmark = pytest.mark.e2e


def _login(client, store, chat_id: str) -> None:
    """Sessione browser autenticata, come negli altri test API della dashboard."""
    store.add_user(chat_id=chat_id, username="labels-api", storage_backend="postgres")
    with client.session_transaction() as session:
        session["user_logged_in"] = True
        session["chat_id"] = chat_id
        session["token_version"] = store.get_token_version(chat_id)


def _csrf(client) -> str:
    return client.get("/api/csrf-token").json["csrf_token"]


def _seed_expense(store, chat_id: str, name: str, category_id: int | None = None,
                  amount: str = "10.00") -> int:
    """Crea una spesa passando dal normalizer, come farebbe il bot."""
    from src.expense_label_normalizer import assign_label_cluster
    from src.storage.models import Expense

    with store.Session() as session:
        cluster = assign_label_cluster(session, chat_id, name, category_id)
        session.add(Expense(
            user_id=chat_id,
            expense_date=date.today(),
            amount=Decimal(amount),
            name=name,
            category_id=category_id,
            label_cluster_id=cluster.cluster_id,
        ))
        session.commit()
        return cluster.cluster_id


# ---------------------------------------------------------------------------
# Lettura
# ---------------------------------------------------------------------------

def test_variants_are_computed_from_real_expenses(client) -> None:
    """I chip mostrati vengono dalle spese vive, non da variant_counts."""
    from src.dashboard.app import store

    owner = "labels_variants_owner"
    _login(client, store, owner)
    cluster_id = _seed_expense(store, owner, "Ape", category_id=1)
    _seed_expense(store, owner, "Ape 50 tagliando", category_id=1)

    response = client.get(f"/api/expense-labels/clusters/{cluster_id}/variants")

    assert response.status_code == 200
    texts = {v["text"] for v in response.json["variants"]}
    assert texts == {"Ape", "Ape 50 tagliando"}
    assert all(v["count"] == 1 for v in response.json["variants"])


def test_clusters_listing_can_filter_by_category(client) -> None:
    from src.dashboard.app import store

    owner = "labels_clusters_owner"
    _login(client, store, owner)
    _seed_expense(store, owner, "Coca Cola", category_id=1)
    _seed_expense(store, owner, "Benzina", category_id=2)

    response = client.get("/api/expense-labels/clusters?category_id=1")

    assert response.status_code == 200
    assert {c["category_id"] for c in response.json["clusters"]} == {1}


def test_variants_of_another_user_cluster_return_404(client) -> None:
    from src.dashboard.app import store

    owner, intruder = "labels_owner_a", "labels_intruder_a"
    store.add_user(chat_id=owner, username="labels-owner", storage_backend="postgres")
    cluster_id = _seed_expense(store, owner, "Coca Cola", category_id=1)
    _login(client, store, intruder)

    response = client.get(f"/api/expense-labels/clusters/{cluster_id}/variants")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Scrittura
# ---------------------------------------------------------------------------

def test_split_creates_new_cluster_and_survives_next_expense(client) -> None:
    """Il caso che la feature esiste per risolvere, end-to-end via HTTP."""
    from src.dashboard.app import store

    owner = "labels_split_owner"
    _login(client, store, owner)
    csrf = _csrf(client)
    cluster_id = _seed_expense(store, owner, "Ape", category_id=1)
    _seed_expense(store, owner, "Ape 50 tagliando", category_id=1)

    response = client.post(
        "/api/expense-labels/split",
        json={"cluster_id": cluster_id, "variants": ["Ape 50 tagliando"]},
        headers={"X-CSRFToken": csrf},
    )

    assert response.status_code == 201
    new_cluster_id = response.json["cluster_id"]
    assert new_cluster_id != cluster_id

    # La spesa successiva con lo stesso testo non deve tornare nel gruppo sbagliato.
    assert _seed_expense(store, owner, "Ape 50 tagliando", category_id=1) == new_cluster_id


def test_merge_moves_expenses_and_is_idempotent(client) -> None:
    from src.dashboard.app import store

    owner = "labels_merge_owner"
    _login(client, store, owner)
    csrf = _csrf(client)
    target = _seed_expense(store, owner, "Coca Cola", category_id=1)
    source = _seed_expense(store, owner, "Bicicletta", category_id=1)

    first = client.post(
        "/api/expense-labels/merge",
        json={"target_cluster_id": target, "source_cluster_ids": [source]},
        headers={"X-CSRFToken": csrf},
    )
    assert first.status_code == 200
    assert first.json["moved_expenses"] == 1

    second = client.post(
        "/api/expense-labels/merge",
        json={"target_cluster_id": target, "source_cluster_ids": [source]},
        headers={"X-CSRFToken": csrf},
    )
    assert second.status_code == 200
    assert second.json["merged"] == 0


def test_clusters_listing_exposes_the_voices_of_each_group(client) -> None:
    """La lista di "Unisci" deve mostrare quali voci contiene ogni gruppo."""
    from src.dashboard.app import store

    owner = "labels_expand_owner"
    _login(client, store, owner)
    _seed_expense(store, owner, "Coca Cola", category_id=1, amount="5.00")
    _seed_expense(store, owner, "Coca coca", category_id=1, amount="7.00")

    response = client.get("/api/expense-labels/clusters?category_id=1")

    cluster = response.json["clusters"][0]
    assert {v["text"] for v in cluster["variants"]} == {"Coca Cola", "Coca coca"}
    # Il dettaglio dei movimenti arriva da /variants quando si apre il gruppo: qui
    # servono solo le voci, così l'elenco resta leggero con molto storico.
    assert "expenses" not in cluster["variants"][0]


def test_clusters_listing_counts_expenses_outside_the_period(client) -> None:
    """I numeri devono descrivere tutto il gruppo, non solo il periodo mostrato.

    L'unione sposta l'intero gruppo: mostrare i soli totali del periodo faceva
    credere di spostare una spesa quando se ne spostavano quattro.
    """
    from src.dashboard.app import store
    from src.expense_label_normalizer import assign_label_cluster
    from src.storage.models import Expense

    owner = "labels_period_owner"
    _login(client, store, owner)
    cluster_id = _seed_expense(store, owner, "Coca Cola", category_id=1, amount="5.00")
    with store.Session() as session:
        session.add(Expense(
            user_id=owner, expense_date=date(2020, 1, 5), amount=Decimal("11.00"),
            name="Coca Cola vecchia", category_id=1, label_cluster_id=cluster_id,
        ))
        session.commit()
    assert assign_label_cluster  # la spesa storica è agganciata allo stesso gruppo

    response = client.get("/api/expense-labels/clusters?months=1&category_id=1")

    cluster = next(c for c in response.json["clusters"] if c["id"] == cluster_id)
    assert cluster["count"] == 2
    assert cluster["total"] == 16.0
    assert {v["text"] for v in cluster["variants"]} == {"Coca Cola", "Coca Cola vecchia"}


def test_partial_merge_keeps_the_source_group_alive(client) -> None:
    from src.dashboard.app import store

    owner = "labels_partial_owner"
    _login(client, store, owner)
    csrf = _csrf(client)
    target = _seed_expense(store, owner, "Spritz", category_id=1)
    source = _seed_expense(store, owner, "Coca Cola", category_id=1)
    _seed_expense(store, owner, "Coca coca", category_id=1)

    response = client.post(
        "/api/expense-labels/merge",
        json={
            "target_cluster_id": target,
            "source_cluster_ids": [source],
            "source_variants": {str(source): ["Coca Cola"]},
        },
        headers={"X-CSRFToken": csrf},
    )

    assert response.status_code == 200
    assert response.json["merged"] == 0
    variants = client.get(f"/api/expense-labels/clusters/{source}/variants").json["variants"]
    assert {v["text"] for v in variants} == {"Coca coca"}


@pytest.mark.parametrize("bad_variants", [
    "Coca Cola",
    {"abc": ["Coca Cola"]},
    {"1": []},
    {"1": [123]},
])
def test_merge_rejects_malformed_source_variants(client, bad_variants) -> None:
    from src.dashboard.app import store

    _login(client, store, "labels_badvariants_owner")
    csrf = _csrf(client)

    response = client.post(
        "/api/expense-labels/merge",
        json={"target_cluster_id": 1, "source_cluster_ids": [2], "source_variants": bad_variants},
        headers={"X-CSRFToken": csrf},
    )

    assert response.status_code == 400


def test_cross_category_merge_is_rejected(client) -> None:
    from src.dashboard.app import store

    owner = "labels_crosscat_owner"
    _login(client, store, owner)
    csrf = _csrf(client)
    target = _seed_expense(store, owner, "Coca Cola", category_id=1)
    other = _seed_expense(store, owner, "Coca Cola", category_id=2)

    response = client.post(
        "/api/expense-labels/merge",
        json={"target_cluster_id": target, "source_cluster_ids": [other]},
        headers={"X-CSRFToken": csrf},
    )

    assert response.status_code == 400
    assert response.json["code"] == "category_mismatch"


def test_merge_of_another_user_cluster_returns_404(client) -> None:
    from src.dashboard.app import store

    owner, intruder = "labels_owner_b", "labels_intruder_b"
    store.add_user(chat_id=owner, username="labels-owner-b", storage_backend="postgres")
    victim = _seed_expense(store, owner, "Coca Cola", category_id=1)
    _login(client, store, intruder)
    csrf = _csrf(client)

    response = client.post(
        "/api/expense-labels/merge",
        json={"target_cluster_id": victim, "source_cluster_ids": [victim + 1]},
        headers={"X-CSRFToken": csrf},
    )

    assert response.status_code == 404


@pytest.mark.parametrize("payload", [
    {},
    {"target_cluster_id": "12", "source_cluster_ids": [1]},
    {"target_cluster_id": 12, "source_cluster_ids": []},
    {"target_cluster_id": 12, "source_cluster_ids": [12]},
    {"target_cluster_id": 12, "source_cluster_ids": list(range(21))},
])
def test_merge_rejects_malformed_payloads(client, payload) -> None:
    from src.dashboard.app import store

    _login(client, store, "labels_badpayload_owner")
    csrf = _csrf(client)

    response = client.post(
        "/api/expense-labels/merge", json=payload, headers={"X-CSRFToken": csrf},
    )

    assert response.status_code == 400


def test_split_rejects_unknown_variant_without_echoing_it(client, caplog) -> None:
    """Il testo inviato dal client non deve tornare nella risposta né nei log."""
    from src.dashboard.app import store

    owner = "labels_echo_owner"
    _login(client, store, owner)
    csrf = _csrf(client)
    cluster_id = _seed_expense(store, owner, "Ape", category_id=1)
    secret = "Regalo per Giulia"

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/api/expense-labels/split",
            json={"cluster_id": cluster_id, "variants": [secret]},
            headers={"X-CSRFToken": csrf},
        )

    assert response.status_code == 400
    assert response.json["code"] == "invalid_variants"
    assert secret not in response.get_data(as_text=True)
    assert secret not in caplog.text


def test_successful_split_does_not_log_expense_text(client, caplog) -> None:
    from src.dashboard.app import store

    owner = "labels_nolog_owner"
    _login(client, store, owner)
    csrf = _csrf(client)
    cluster_id = _seed_expense(store, owner, "Ape", category_id=1)
    _seed_expense(store, owner, "Ape 50 tagliando", category_id=1)

    with caplog.at_level(logging.INFO):
        response = client.post(
            "/api/expense-labels/split",
            json={"cluster_id": cluster_id, "variants": ["Ape 50 tagliando"]},
            headers={"X-CSRFToken": csrf},
        )

    assert response.status_code == 201
    assert "Ape 50 tagliando" not in caplog.text


# ---------------------------------------------------------------------------
# Switch "raggruppa" / "per nome"
# ---------------------------------------------------------------------------

def test_top_merchants_group_flag_switches_aggregation(client) -> None:
    from src.dashboard.app import store

    owner = "labels_group_owner"
    _login(client, store, owner)
    # "Ape" e "Ape 50 tagliando" finiscono nello stesso cluster (partial_ratio 100).
    _seed_expense(store, owner, "Ape", category_id=1)
    _seed_expense(store, owner, "Ape 50 tagliando", category_id=1)

    grouped = client.get("/api/analytics/top-merchants?group=1")
    raw = client.get("/api/analytics/top-merchants?group=0")

    assert grouped.json["grouped"] is True
    assert len(grouped.json["merchants"]) == 1
    assert raw.json["grouped"] is False
    assert {m["name"] for m in raw.json["merchants"]} == {"Ape", "Ape 50 tagliando"}


def test_top_merchants_falls_back_to_user_preference(client) -> None:
    from src.dashboard.app import store

    owner = "labels_pref_owner"
    _login(client, store, owner)
    _seed_expense(store, owner, "Ape", category_id=1)
    _seed_expense(store, owner, "Ape 50 tagliando", category_id=1)
    store.update_user_preferences(owner, {"analytics_group_labels": False})

    response = client.get("/api/analytics/top-merchants")

    assert response.json["grouped"] is False
    assert len(response.json["merchants"]) == 2


def test_cluster_id_is_null_when_row_spans_multiple_clusters(client) -> None:
    """Senza un cluster unico la UI non può offrire la correzione: deve saperlo."""
    from src.dashboard.app import store

    owner = "labels_multicluster_owner"
    _login(client, store, owner)
    # Stesso testo in due categorie -> due cluster distinti (guardrail di categoria).
    _seed_expense(store, owner, "Coca Cola", category_id=1)
    _seed_expense(store, owner, "Coca Cola", category_id=2)

    response = client.get("/api/analytics/top-merchants?group=0")

    row = next(m for m in response.json["merchants"] if m["name"] == "Coca Cola")
    assert row["cluster_id"] is None


def test_preference_round_trips_through_user_preferences_api(client) -> None:
    from src.dashboard.app import store

    owner = "labels_prefapi_owner"
    _login(client, store, owner)
    csrf = _csrf(client)

    updated = client.put(
        "/api/user/preferences",
        json={"analytics_group_labels": False},
        headers={"X-CSRFToken": csrf},
    )

    assert updated.status_code == 200
    assert client.get("/api/user/preferences").json["analytics_group_labels"] is False
