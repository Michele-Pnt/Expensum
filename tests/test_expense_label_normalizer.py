"""
tests/test_expense_label_normalizer.py — Test per src/expense_label_normalizer.py.

Usa SQLite in-memory (engine module-scoped, reset via drop_all/create_all) perché
`assign_label_cluster` interroga e scrive `ExpenseLabelCluster` via SQLAlchemy Session.
Nessun mocking di servizi esterni necessario: la funzione è pura logica DB + rapidfuzz.
"""

from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.expense_label_normalizer import (
    LabelClusterError,
    assign_label_cluster,
    lookup_override,
    merge_clusters,
    split_variants,
)
from src.storage.models import Expense, ExpenseLabelCluster, ExpenseLabelOverride
from src.user_store import Base, User

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def db_engine():
    """Engine SQLite in-memory condiviso per tutto il modulo."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Schema azzerato e utente di test reinserito a ogni test."""
    Base.metadata.drop_all(db_engine)
    Base.metadata.create_all(db_engine)
    Session = sessionmaker(bind=db_engine)
    session = Session()

    session.add(User(chat_id="test_user_1", username="testuser", is_active=True))
    session.add(User(chat_id="test_user_2", username="otheruser", is_active=True))
    session.commit()

    yield session
    session.close()


def _add_expense(session, name, category_id=1, cluster_id=None, user_id="test_user_1"):
    """Crea una spesa agganciata a un cluster, come farebbe `create_expense`."""
    expense = Expense(
        user_id=user_id,
        expense_date=date(2026, 8, 12),
        amount=Decimal("10.00"),
        name=name,
        category_id=category_id,
        label_cluster_id=cluster_id,
    )
    session.add(expense)
    session.flush()
    return expense


def _seed(session, name, category_id=1, user_id="test_user_1"):
    """Registra una spesa esattamente come fa `PostgresStorage.create_expense`.

    Le correzioni manuali leggono le spese reali, non `variant_counts`: un cluster
    senza spese è uno stato che in produzione non esiste, e testarlo darebbe
    garanzie false.
    """
    result = assign_label_cluster(session, user_id, name, category_id)
    _add_expense(session, name, category_id, result.cluster_id, user_id)
    return result


# ---------------------------------------------------------------------------
# 1. Creazione nuovo cluster
# ---------------------------------------------------------------------------

class TestNewCluster:
    def test_creates_cluster_when_no_candidates(self, db_session):
        """Nessun cluster esistente -> se ne crea uno nuovo con l'ancora = raw_name."""
        result = assign_label_cluster(db_session, "test_user_1", "Coca Cola", category_id=1)

        assert result.created is True
        assert result.anchor_text == "Coca Cola"
        cluster = db_session.query(ExpenseLabelCluster).get(result.cluster_id)
        assert cluster.variant_counts == {"Coca Cola": 1}

    def test_creates_new_cluster_when_score_below_threshold(self, db_session):
        """Un testo troppo diverso dall'ancora esistente non deve unirsi: nuovo cluster."""
        first = assign_label_cluster(db_session, "test_user_1", "Pizza Margherita", category_id=1)
        second = assign_label_cluster(db_session, "test_user_1", "Bicicletta nuova", category_id=1)

        assert second.created is True
        assert second.cluster_id != first.cluster_id


# ---------------------------------------------------------------------------
# 2. Merge quando supera la soglia
# ---------------------------------------------------------------------------

class TestMerge:
    def test_merges_similar_variant_into_existing_cluster(self, db_session):
        """'coca cola' e 'coca-cola' sono abbastanza simili da unirsi (score >= 85)."""
        first = assign_label_cluster(db_session, "test_user_1", "Coca Cola", category_id=1)
        second = assign_label_cluster(db_session, "test_user_1", "Coca-Cola", category_id=1)

        assert second.created is False
        assert second.cluster_id == first.cluster_id

    def test_custom_threshold_prevents_merge(self, db_session):
        """Una soglia esplicita più alta della soglia di default deve poter bloccare un
        merge che altrimenti avverrebbe con la soglia di default."""
        assign_label_cluster(db_session, "test_user_1", "Coca Cola", category_id=1)
        # score reale coca cola/coca-cola ~ 88.9: con soglia 95 non deve unirsi
        result = assign_label_cluster(
            db_session, "test_user_1", "Coca-Cola", category_id=1, threshold=95
        )
        assert result.created is True


# ---------------------------------------------------------------------------
# 3. Guardrail categoria
# ---------------------------------------------------------------------------

class TestCategoryGuardrail:
    def test_same_text_different_category_never_merges(self, db_session):
        """Stesso testo esatto ma categoria diversa -> cluster separati by design."""
        first = assign_label_cluster(db_session, "test_user_1", "Coca Cola", category_id=1)
        second = assign_label_cluster(db_session, "test_user_1", "Coca Cola", category_id=2)

        assert second.created is True
        assert second.cluster_id != first.cluster_id

    def test_none_category_is_its_own_bucket(self, db_session):
        """category_id=None è trattato come un valore di categoria a sé, coerente
        (non deve confondersi con categorie numeriche esistenti)."""
        with_cat = assign_label_cluster(db_session, "test_user_1", "Varie", category_id=1)
        without_cat = assign_label_cluster(db_session, "test_user_1", "Varie", category_id=None)

        assert without_cat.created is True
        assert without_cat.cluster_id != with_cat.cluster_id


# ---------------------------------------------------------------------------
# 4. Aggiornamento ancora alla variante più frequente
# ---------------------------------------------------------------------------

class TestAnchorUpdates:
    def test_anchor_switches_to_most_frequent_variant(self, db_session):
        """L'ancora deve aggiornarsi alla variante vista più spesso finora."""
        first = assign_label_cluster(db_session, "test_user_1", "coca", category_id=1)
        assert first.anchor_text == "coca"

        # "coca cola" arriva due volte: deve diventare la nuova ancora (2 > 1)
        assign_label_cluster(db_session, "test_user_1", "coca cola", category_id=1)
        result = assign_label_cluster(db_session, "test_user_1", "coca cola", category_id=1)

        assert result.anchor_text == "coca cola"
        cluster = db_session.query(ExpenseLabelCluster).get(result.cluster_id)
        assert cluster.variant_counts == {"coca": 1, "coca cola": 2}

    def test_anchor_stays_when_incumbent_still_most_frequent(self, db_session):
        """Se la variante entrante non supera il conteggio dell'ancora attuale, l'ancora
        non cambia (nessun flip inutile per un pareggio o una minoranza)."""
        assign_label_cluster(db_session, "test_user_1", "coca cola", category_id=1)
        assign_label_cluster(db_session, "test_user_1", "coca cola", category_id=1)
        result = assign_label_cluster(db_session, "test_user_1", "coca", category_id=1)

        assert result.anchor_text == "coca cola"


# ---------------------------------------------------------------------------
# 5. Input vuoto/None
# ---------------------------------------------------------------------------

class TestEmptyInput:
    def test_empty_string_does_not_raise_and_creates_cluster(self, db_session):
        result = assign_label_cluster(db_session, "test_user_1", "", category_id=1)
        assert result.created is True
        assert result.anchor_text == ""

    def test_none_raw_name_does_not_raise(self, db_session):
        """Fix applicato in sessione: `raw_name=None` viene trattato come stringa vuota
        prima di tutto il resto, così `ExpenseLabelCluster.anchor_text` (NOT NULL) riceve
        sempre una stringa valida — coerente con quanto il docstring promette."""
        result = assign_label_cluster(db_session, "test_user_1", None, category_id=1)
        assert result.created is True
        assert result.anchor_text == ""

    def test_two_empty_strings_reuse_the_same_empty_cluster(self, db_session):
        """Fix applicato in sessione (suggerito in review): due nomi vuoti non devono
        aprire un cluster distinto ciascuno (altrimenti N spese senza nome -> N cluster
        identici, che inquinerebbero `singleton_clusters` in dashboard) — riusano lo
        stesso cluster "vuoto" per utente+categoria, senza passare da rapidfuzz
        (`partial_ratio("", x)` darebbe 100 e unirebbe a un cluster arbitrario)."""
        first = assign_label_cluster(db_session, "test_user_1", "", category_id=1)
        second = assign_label_cluster(db_session, "test_user_1", "", category_id=1)
        assert second.created is False
        assert second.cluster_id == first.cluster_id


# ---------------------------------------------------------------------------
# 6. Caso "Ape" / "Ape 50" / "Aperitivo" — un bug reale (Ape 50) + un compromesso
#    accettato consapevolmente (Ape da solo), non confonderli
# ---------------------------------------------------------------------------

class TestApeAperitivoRegression:
    """Il caso "Ape 50" (scooter, con il numero) era un bug reale trovato e corretto in
    sessione — vedi i due test sotto, devono restare verdi.

    "Ape" da solo (senza "50") è invece un compromesso di design discusso e accettato
    esplicitamente, non un bug residuo: con `fuzz.partial_ratio` una stringa più corta
    che è sottostringa esatta di una più lunga ottiene sempre punteggio 100 — "ape" è
    prefisso di "aperitivo" tanto quanto lo è di un'ipotetica abbreviazione legittima
    (l'utente scrive "ape" intendendo "aperitivo"). Non esiste una soglia puramente
    testuale che distingua i due casi senza rompere quello legittimo (verificato: la
    differenza di caratteri tra "ape"/"aperitivo" non è separabile da quella tra
    "acqua"/"acqua tonica", stesso tipo di ambiguità). La rete di sicurezza scelta è
    il guardrail di categoria (stesso testo in categorie diverse resta separato) più
    l'osservabilità in dashboard admin, non un fix testuale qui. Il test sotto
    documenta il comportamento voluto — se un giorno cambia, va rivalutato come scelta
    di design, non trattato come una regressione da correggere al volo."""

    def test_ape_50_does_not_merge_with_aperitivo(self, db_session):
        aperitivo = assign_label_cluster(db_session, "test_user_1", "Aperitivo", category_id=1)
        ape_50 = assign_label_cluster(db_session, "test_user_1", "Ape 50", category_id=1)

        assert ape_50.created is True
        assert ape_50.cluster_id != aperitivo.cluster_id

    def test_aperitivo_does_not_merge_with_ape_50(self, db_session):
        """Stesso scenario ma con ordine di arrivo invertito (ape 50 prima)."""
        ape_50 = assign_label_cluster(db_session, "test_user_1", "Ape 50", category_id=1)
        aperitivo = assign_label_cluster(db_session, "test_user_1", "Aperitivo", category_id=1)

        assert aperitivo.created is True
        assert aperitivo.cluster_id != ape_50.cluster_id

    def test_bare_ape_merges_with_aperitivo_accepted_tradeoff(self, db_session):
        """'Ape' (senza '50') è sottostringa esatta di 'Aperitivo' ->
        fuzz.partial_ratio('ape', 'aperitivo') = 100, sopra soglia. Comportamento
        VOLUTO nella stessa categoria (vedi docstring della classe) — non un bug."""
        aperitivo = assign_label_cluster(db_session, "test_user_1", "Aperitivo", category_id=1)
        ape = assign_label_cluster(db_session, "test_user_1", "Ape", category_id=1)

        assert ape.created is False
        assert ape.cluster_id == aperitivo.cluster_id


# ---------------------------------------------------------------------------
# 7. Correzione manuale — regole di override
# ---------------------------------------------------------------------------

class TestOverrideLookup:
    def test_override_wins_over_fuzzy_match(self, db_session):
        """Con una regola attiva il fuzzy non viene nemmeno calcolato."""
        aperitivo = assign_label_cluster(db_session, "test_user_1", "Aperitivo", category_id=1)
        other = assign_label_cluster(db_session, "test_user_1", "Bicicletta", category_id=1)
        db_session.add(ExpenseLabelOverride(
            user_id="test_user_1", category_id=1, normalized_text="ape",
            cluster_id=other.cluster_id, source="split",
        ))
        db_session.flush()

        result = assign_label_cluster(db_session, "test_user_1", "Ape", category_id=1)

        assert result.cluster_id == other.cluster_id
        assert result.cluster_id != aperitivo.cluster_id

    def test_override_matches_on_normalized_text(self, db_session):
        """La regola su 'Ape 50' vale anche per 'ape  50' scritto dopo."""
        target = assign_label_cluster(db_session, "test_user_1", "Bicicletta", category_id=1)
        db_session.add(ExpenseLabelOverride(
            user_id="test_user_1", category_id=1, normalized_text="ape 50",
            cluster_id=target.cluster_id, source="split",
        ))
        db_session.flush()

        result = assign_label_cluster(db_session, "test_user_1", "  Ape   50 ", category_id=1)

        assert result.cluster_id == target.cluster_id

    def test_override_is_isolated_per_user(self, db_session):
        """La regola di un utente non deve influenzare le spese di un altro."""
        target = assign_label_cluster(db_session, "test_user_1", "Bicicletta", category_id=1)
        db_session.add(ExpenseLabelOverride(
            user_id="test_user_1", category_id=1, normalized_text="ape",
            cluster_id=target.cluster_id, source="split",
        ))
        db_session.flush()

        result = assign_label_cluster(db_session, "test_user_2", "Ape", category_id=1)

        assert result.created is True
        assert result.cluster_id != target.cluster_id

    def test_override_does_not_cross_categories(self, db_session):
        """Scoping per categoria: la regola in cat 1 non si applica in cat 2."""
        target = assign_label_cluster(db_session, "test_user_1", "Bicicletta", category_id=1)
        db_session.add(ExpenseLabelOverride(
            user_id="test_user_1", category_id=1, normalized_text="ape",
            cluster_id=target.cluster_id, source="split",
        ))
        db_session.flush()

        result = assign_label_cluster(db_session, "test_user_1", "Ape", category_id=2)

        assert result.created is True
        assert result.cluster_id != target.cluster_id

    def test_orphan_override_falls_back_to_fuzzy(self, db_session):
        """Regola che punta a un cluster sparito: si ricade sul fuzzy, senza eccezioni."""
        aperitivo = assign_label_cluster(db_session, "test_user_1", "Aperitivo", category_id=1)
        db_session.add(ExpenseLabelOverride(
            user_id="test_user_1", category_id=1, normalized_text="ape",
            cluster_id=9999, source="split",
        ))
        db_session.flush()

        result = assign_label_cluster(db_session, "test_user_1", "Ape", category_id=1)

        assert result.cluster_id == aperitivo.cluster_id


# ---------------------------------------------------------------------------
# 8. Dividi — è il motivo per cui esistono le regole di override
# ---------------------------------------------------------------------------

class TestSplitDurability:
    """Il caso che la feature esiste per risolvere: 'Ape 50 tagliando' finita insieme
    agli aperitivi perché partial_ratio('ape', 'ape 50 tagliando') = 100. Dopo la
    separazione manuale, la spesa SUCCESSIVA con lo stesso testo non deve tornare
    nel gruppo sbagliato — è ciò che distingue una correzione durevole da una
    riassegnazione una tantum."""

    def test_split_survives_next_expense_with_same_text(self, db_session):
        ape = _seed(db_session, "Ape", category_id=1)
        tagliando = _seed(
            db_session, "Ape 50 tagliando", category_id=1)
        assert tagliando.cluster_id == ape.cluster_id  # il falso positivo di partenza

        result = split_variants(
            db_session, "test_user_1", ape.cluster_id, ["Ape 50 tagliando"])

        again = _seed(
            db_session, "Ape 50 tagliando", category_id=1)
        assert again.cluster_id == result.new_cluster_id

        still_ape = _seed(db_session, "Ape", category_id=1)
        assert still_ape.cluster_id == ape.cluster_id


class TestSplitMechanics:
    def test_moves_only_expenses_with_matching_name(self, db_session):
        ape = _seed(db_session, "Ape", category_id=1)
        _seed(db_session, "Ape 50 tagliando", category_id=1)
        keep = _add_expense(db_session, "Ape", cluster_id=ape.cluster_id)
        move = _add_expense(db_session, "Ape 50 tagliando", cluster_id=ape.cluster_id)

        result = split_variants(
            db_session, "test_user_1", ape.cluster_id, ["Ape 50 tagliando"])

        db_session.refresh(keep)
        db_session.refresh(move)
        assert keep.label_cluster_id == ape.cluster_id
        assert move.label_cluster_id == result.new_cluster_id
        # Due spese con quel nome (quella di `_seed` e quella aggiunta qui): entrambe.
        assert result.moved_expenses == 2

    def test_new_cluster_keeps_category_and_locks_anchor(self, db_session):
        ape = _seed(db_session, "Ape", category_id=7)
        _seed(db_session, "Ape 50 tagliando", category_id=7)

        result = split_variants(
            db_session, "test_user_1", ape.cluster_id, ["Ape 50 tagliando"])

        new_cluster = db_session.get(ExpenseLabelCluster, result.new_cluster_id)
        assert new_cluster.category_id == 7
        assert new_cluster.anchor_locked is True
        assert new_cluster.variant_counts == {"Ape 50 tagliando": 1}

    def test_source_unlocks_when_its_anchor_is_moved_away(self, db_session):
        """Se l'ancora bloccata se ne va con le varianti spostate, il blocco cade."""
        ape = _seed(db_session, "Ape", category_id=1)
        _seed(db_session, "Ape 50 tagliando", category_id=1)
        cluster = db_session.get(ExpenseLabelCluster, ape.cluster_id)
        cluster.anchor_text = "Ape 50 tagliando"
        cluster.anchor_locked = True
        db_session.flush()

        split_variants(db_session, "test_user_1", ape.cluster_id, ["Ape 50 tagliando"])

        db_session.refresh(cluster)
        assert cluster.anchor_locked is False
        assert cluster.anchor_text == "Ape"

    def test_variants_differing_only_by_case_move_together(self, db_session):
        """Regressione: due grafie della stessa voce condividono la chiave di override.

        Trattarle come varianti separate faceva sovrascrivere una regola con l'altra,
        e lo split si disfaceva da solo al primo inserimento successivo."""
        ape = _seed(db_session, "Ape", category_id=1)
        _seed(db_session, "Ape 50 tagliando", category_id=1)
        _seed(db_session, "ape 50  TAGLIANDO", category_id=1)

        result = split_variants(
            db_session, "test_user_1", ape.cluster_id, ["Ape 50 tagliando"])

        new_cluster = db_session.get(ExpenseLabelCluster, result.new_cluster_id)
        assert set(new_cluster.variant_counts) == {"Ape 50 tagliando", "ape 50  TAGLIANDO"}
        again = _seed(
            db_session, "Ape 50 tagliando", category_id=1)
        assert again.cluster_id == result.new_cluster_id

    def test_split_works_after_an_expense_was_renamed(self, db_session):
        """Regressione dal DB reale (cluster 15, utente demo).

        Rinominare una spesa non aggiorna `variant_counts` del cluster: il pannello
        mostrava "Coca coca" (letta dalle spese) mentre la validazione cercava nella
        vecchia grafia "Coca cola", e la separazione falliva con "questa voce non
        esiste più" su una voce visibile a schermo."""
        cluster = _seed(db_session, "Coca Cola", category_id=1)
        _seed(db_session, "Coca cola", category_id=1)
        renamed = (
            db_session.query(Expense).filter(Expense.name == "Coca cola").one()
        )
        renamed.name = "Coca coca"  # rinomina: variant_counts resta indietro
        db_session.flush()

        result = split_variants(
            db_session, "test_user_1", cluster.cluster_id, ["Coca coca"])

        db_session.refresh(renamed)
        assert renamed.label_cluster_id == result.new_cluster_id
        source = db_session.get(ExpenseLabelCluster, cluster.cluster_id)
        assert "Coca coca" not in source.variant_counts

    def test_split_resyncs_counts_after_a_deleted_expense(self, db_session):
        """Una spesa cancellata non deve lasciare voci fantasma nei conteggi."""
        cluster = _seed(db_session, "Ape", category_id=1)
        _seed(db_session, "Ape 50 tagliando", category_id=1)
        _seed(db_session, "Ape 50 revisione", category_id=1)
        ghost = (
            db_session.query(Expense).filter(Expense.name == "Ape 50 revisione").one()
        )
        db_session.delete(ghost)
        db_session.flush()

        split_variants(db_session, "test_user_1", cluster.cluster_id, ["Ape 50 tagliando"])

        source = db_session.get(ExpenseLabelCluster, cluster.cluster_id)
        assert "Ape 50 revisione" not in source.variant_counts
        assert source.variant_counts == {"Ape": 1}

    def test_unknown_variant_is_rejected(self, db_session):
        ape = _seed(db_session, "Ape", category_id=1)
        _seed(db_session, "Ape 50 tagliando", category_id=1)

        with pytest.raises(LabelClusterError) as exc:
            split_variants(db_session, "test_user_1", ape.cluster_id, ["Mai vista"])
        assert exc.value.code == "invalid_variants"

    def test_splitting_every_variant_is_rejected(self, db_session):
        ape = _seed(db_session, "Ape", category_id=1)
        _seed(db_session, "Ape 50 tagliando", category_id=1)

        with pytest.raises(LabelClusterError) as exc:
            split_variants(
                db_session, "test_user_1", ape.cluster_id, ["Ape", "Ape 50 tagliando"])
        assert exc.value.code == "split_all_variants"

    def test_cluster_of_another_user_is_not_found(self, db_session):
        ape = _seed(db_session, "Ape", category_id=1)
        _seed(db_session, "Ape 50 tagliando", category_id=1)

        with pytest.raises(LabelClusterError) as exc:
            split_variants(
                db_session, "test_user_2", ape.cluster_id, ["Ape 50 tagliando"])
        assert exc.value.code == "cluster_not_found"

    def test_second_split_of_same_variants_is_rejected(self, db_session):
        """Doppio invio: le varianti non sono più nel cluster di partenza."""
        ape = _seed(db_session, "Ape", category_id=1)
        _seed(db_session, "Ape 50 tagliando", category_id=1)
        split_variants(db_session, "test_user_1", ape.cluster_id, ["Ape 50 tagliando"])

        with pytest.raises(LabelClusterError) as exc:
            split_variants(db_session, "test_user_1", ape.cluster_id, ["Ape 50 tagliando"])
        assert exc.value.code == "invalid_variants"


# ---------------------------------------------------------------------------
# 9. Unisci
# ---------------------------------------------------------------------------

class TestMergeClusters:
    def test_merges_counts_expenses_and_deletes_sources(self, db_session):
        coca = _seed(db_session, "Coca Cola", category_id=1)
        bici = _seed(db_session, "Bicicletta", category_id=1)
        moved = _add_expense(db_session, "Bicicletta", cluster_id=bici.cluster_id)

        result = merge_clusters(
            db_session, "test_user_1", coca.cluster_id, [bici.cluster_id])

        db_session.refresh(moved)
        assert moved.label_cluster_id == coca.cluster_id
        # Due spese "Bicicletta": quella di `_seed` e quella aggiunta qui.
        assert result.moved_expenses == 2
        assert result.absorbed_cluster_ids == [bici.cluster_id]
        assert db_session.get(ExpenseLabelCluster, bici.cluster_id) is None
        target = db_session.get(ExpenseLabelCluster, coca.cluster_id)
        # Ricalcolato dalle spese reali: due "Bicicletta", una "Coca Cola".
        assert target.variant_counts == {"Coca Cola": 1, "Bicicletta": 2}

    def test_chosen_anchor_is_locked_and_survives_new_expenses(self, db_session):
        """L'etichetta scelta dall'utente non deve cedere alla variante più frequente."""
        coca = _seed(db_session, "Coca Cola", category_id=1)
        bici = _seed(db_session, "Bicicletta", category_id=1)
        merge_clusters(
            db_session, "test_user_1", coca.cluster_id, [bici.cluster_id],
            anchor_text="Coca Cola",
        )

        for _ in range(10):
            _seed(db_session, "Bicicletta", category_id=1)

        target = db_session.get(ExpenseLabelCluster, coca.cluster_id)
        assert target.anchor_locked is True
        assert target.anchor_text == "Coca Cola"

    def test_new_expense_of_absorbed_variant_lands_on_target(self, db_session):
        coca = _seed(db_session, "Coca Cola", category_id=1)
        bici = _seed(db_session, "Bicicletta", category_id=1)
        merge_clusters(db_session, "test_user_1", coca.cluster_id, [bici.cluster_id])

        result = _seed(db_session, "Bicicletta", category_id=1)

        assert result.cluster_id == coca.cluster_id

    def test_partial_merge_keeps_the_unselected_variants_in_place(self, db_session):
        """Unione parziale: solo le voci scelte si spostano, il gruppo sopravvive."""
        target = _seed(db_session, "Spritz", category_id=1)
        source = _seed(db_session, "Coca Cola", category_id=1)
        _seed(db_session, "Coca coca", category_id=1)
        moved = _add_expense(db_session, "Coca Cola", cluster_id=source.cluster_id)
        stays = _add_expense(db_session, "Coca coca", cluster_id=source.cluster_id)

        result = merge_clusters(
            db_session, "test_user_1", target.cluster_id, [source.cluster_id],
            source_variants={source.cluster_id: ["Coca Cola"]},
        )

        db_session.refresh(moved)
        db_session.refresh(stays)
        assert moved.label_cluster_id == target.cluster_id
        assert stays.label_cluster_id == source.cluster_id
        assert result.absorbed_cluster_ids == []
        survivor = db_session.get(ExpenseLabelCluster, source.cluster_id)
        assert survivor is not None
        assert set(survivor.variant_counts) == {"Coca coca"}

    def test_partial_merge_pins_both_sides(self, db_session):
        """Le voci restate devono restare: senza regola il fuzzy le riporterebbe via."""
        target = _seed(db_session, "Spritz", category_id=1)
        source = _seed(db_session, "Coca Cola", category_id=1)
        _seed(db_session, "Coca coca", category_id=1)

        merge_clusters(
            db_session, "test_user_1", target.cluster_id, [source.cluster_id],
            source_variants={source.cluster_id: ["Coca Cola"]},
        )

        assert _seed(
            db_session, "Coca Cola", category_id=1
        ).cluster_id == target.cluster_id
        assert _seed(
            db_session, "Coca coca", category_id=1
        ).cluster_id == source.cluster_id

    def test_partial_merge_moves_every_expense_written_the_same_way(self, db_session):
        """L'unità è la voce: due spese con lo stesso nome non si separano mai."""
        target = _seed(db_session, "Spritz", category_id=1)
        source = _seed(db_session, "Coca Cola", category_id=1)
        _seed(db_session, "Coca coca", category_id=1)
        first = _add_expense(db_session, "Coca Cola", cluster_id=source.cluster_id)
        second = _add_expense(db_session, "Coca Cola", cluster_id=source.cluster_id)

        merge_clusters(
            db_session, "test_user_1", target.cluster_id, [source.cluster_id],
            source_variants={source.cluster_id: ["Coca Cola"]},
        )

        db_session.refresh(first)
        db_session.refresh(second)
        assert first.label_cluster_id == second.label_cluster_id == target.cluster_id

    def test_partial_merge_with_all_variants_absorbs_the_source(self, db_session):
        target = _seed(db_session, "Spritz", category_id=1)
        source = _seed(db_session, "Coca Cola", category_id=1)

        result = merge_clusters(
            db_session, "test_user_1", target.cluster_id, [source.cluster_id],
            source_variants={source.cluster_id: ["Coca Cola"]},
        )

        assert result.absorbed_cluster_ids == [source.cluster_id]
        assert db_session.get(ExpenseLabelCluster, source.cluster_id) is None

    def test_partial_merge_rejects_unknown_variant(self, db_session):
        target = _seed(db_session, "Spritz", category_id=1)
        source = _seed(db_session, "Coca Cola", category_id=1)

        with pytest.raises(LabelClusterError) as exc:
            merge_clusters(
                db_session, "test_user_1", target.cluster_id, [source.cluster_id],
                source_variants={source.cluster_id: ["Mai vista"]},
            )
        assert exc.value.code == "invalid_variants"

    def test_cross_category_merge_is_rejected(self, db_session):
        coca = _seed(db_session, "Coca Cola", category_id=1)
        other = _seed(db_session, "Coca Cola", category_id=2)

        with pytest.raises(LabelClusterError) as exc:
            merge_clusters(db_session, "test_user_1", coca.cluster_id, [other.cluster_id])
        assert exc.value.code == "category_mismatch"

    def test_anchor_outside_variants_is_rejected(self, db_session):
        coca = _seed(db_session, "Coca Cola", category_id=1)
        bici = _seed(db_session, "Bicicletta", category_id=1)

        with pytest.raises(LabelClusterError) as exc:
            merge_clusters(
                db_session, "test_user_1", coca.cluster_id, [bici.cluster_id],
                anchor_text="Nome inventato",
            )
        assert exc.value.code == "invalid_anchor"

    def test_target_of_another_user_is_not_found(self, db_session):
        coca = _seed(db_session, "Coca Cola", category_id=1)

        with pytest.raises(LabelClusterError) as exc:
            merge_clusters(db_session, "test_user_2", coca.cluster_id, [])
        assert exc.value.code == "cluster_not_found"

    def test_second_merge_is_idempotent(self, db_session):
        """Doppio invio dalla UI: le sorgenti non esistono più, nessun errore."""
        coca = _seed(db_session, "Coca Cola", category_id=1)
        bici = _seed(db_session, "Bicicletta", category_id=1)
        merge_clusters(db_session, "test_user_1", coca.cluster_id, [bici.cluster_id])
        before = dict(db_session.get(ExpenseLabelCluster, coca.cluster_id).variant_counts)

        result = merge_clusters(
            db_session, "test_user_1", coca.cluster_id, [bici.cluster_id])

        assert result.moved_expenses == 0
        assert result.absorbed_cluster_ids == []
        assert db_session.get(ExpenseLabelCluster, coca.cluster_id).variant_counts == before

    def test_overrides_of_absorbed_cluster_are_repointed(self, db_session):
        """Le regole che puntavano al cluster assorbito devono seguire il target."""
        coca = _seed(db_session, "Coca Cola", category_id=1)
        bici = _seed(db_session, "Bicicletta", category_id=1)
        merge_clusters(db_session, "test_user_1", coca.cluster_id, [bici.cluster_id])

        assert lookup_override(db_session, "test_user_1", "Bicicletta", 1) == coca.cluster_id
        stale = (
            db_session.query(ExpenseLabelOverride)
            .filter_by(cluster_id=bici.cluster_id).count()
        )
        assert stale == 0
