"""
tests/test_gamification_registry.py — Test puri per src/gamification/registry.py.

Nessun DB, nessun mock: verifica solo le invarianti del catalogo dichiarativo.
I test iterano su ACHIEVEMENTS e BY_CODE/BY_METRIC/BY_FAMILY per validare
il contratto pubblico (code stabile), la coerenza dei dati (lingue, metriche,
progressione XP) e le regole architetturali (family, backend, plan).
"""
import pytest

from src.gamification import registry as R
from src.gamification import metrics as M

pytestmark = pytest.mark.unit


class TestAchievementCodeUniqueness:
    """I codici achievement sono identificatori stabili verso app/webapp/DB.

    Rinominarne uno equivale a cancellare l'achievement per tutti gli utenti
    che lo avevano sbloccato. Quindi tutti i code in ACHIEVEMENTS devono essere
    univoci, e BY_CODE deve avere la stessa cardinalità di ACHIEVEMENTS.
    """

    def test_all_codes_are_unique(self):
        """Verifica che len(BY_CODE) == len(ACHIEVEMENTS)."""
        codes = [a.code for a in R.ACHIEVEMENTS]
        assert len(codes) == len(set(codes)), (
            f"Codici duplicati in ACHIEVEMENTS: "
            f"len(ACHIEVEMENTS)={len(codes)}, len(unique)={len(set(codes))}"
        )
        assert len(R.BY_CODE) == len(R.ACHIEVEMENTS), (
            "BY_CODE non sincronizzato con ACHIEVEMENTS"
        )


class TestAchievementTitlesAndDescriptions:
    """Tutti gli achievement hanno testi in italiano e inglese, non vuoti."""

    def test_all_achievements_have_both_languages(self):
        """Verifica che titoli e descrizioni abbiano 'it' e 'en'."""
        for a in R.ACHIEVEMENTS:
            assert "it" in a.titles, f"{a.code}: manca titolo italiano"
            assert "en" in a.titles, f"{a.code}: manca titolo inglese"
            assert "it" in a.descriptions, f"{a.code}: manca descrizione italiana"
            assert "en" in a.descriptions, f"{a.code}: manca descrizione inglese"

    def test_all_text_fields_are_non_empty(self):
        """Verifica che nessun titolo o descrizione sia vuoto."""
        for a in R.ACHIEVEMENTS:
            assert a.titles["it"].strip(), f"{a.code}: titolo italiano vuoto"
            assert a.titles["en"].strip(), f"{a.code}: titolo inglese vuoto"
            assert a.descriptions["it"].strip(), (
                f"{a.code}: descrizione italiana vuota"
            )
            assert a.descriptions["en"].strip(), (
                f"{a.code}: descrizione inglese vuota"
            )


class TestAchievementXP:
    """L'XP è sempre positivo (è il reward dello sblocco)."""

    def test_all_xp_values_are_positive(self):
        """Verifica che xp > 0 per ogni achievement."""
        for a in R.ACHIEVEMENTS:
            assert a.xp > 0, f"{a.code}: xp non positivo ({a.xp})"


class TestAchievementMetrics:
    """Le metriche devono essere in ALL_METRICS o CHANNELS_MIN.

    Gli achievement con metric=None sono sbloccati esplicitamente (no soglia),
    quindi devono avere repeatable=True per permettere sblocchi multipli.
    """

    def test_all_metrics_are_valid(self):
        """Verifica che metric appartenga a ALL_METRICS o sia CHANNELS_MIN."""
        valid_metrics = set(M.ALL_METRICS) | {M.CHANNELS_MIN}
        for a in R.ACHIEVEMENTS:
            if a.metric is not None:
                assert a.metric in valid_metrics, (
                    f"{a.code}: metrica '{a.metric}' non riconosciuta"
                )

    def test_metric_none_implies_repeatable(self):
        """Se metric=None, allora repeatable=True (nessuna soglia da calcolare)."""
        for a in R.ACHIEVEMENTS:
            if a.metric is None:
                assert a.repeatable is True, (
                    f"{a.code}: metric=None ma repeatable={a.repeatable}"
                )


class TestAchievementSupersedes:
    """Il campo supersedes punta a un achievement che esiste e della stessa famiglia."""

    def test_supersedes_points_to_existing_achievement(self):
        """Verifica che ogni supersedes punta a un code in BY_CODE."""
        for a in R.ACHIEVEMENTS:
            if a.supersedes:
                assert a.supersedes in R.BY_CODE, (
                    f"{a.code}: supersedes '{a.supersedes}' non esiste"
                )

    def test_supersedes_is_same_family(self):
        """Verifica che supersedes appartenga alla stessa famiglia."""
        for a in R.ACHIEVEMENTS:
            if a.supersedes:
                superseded = R.BY_CODE[a.supersedes]
                assert a.family == superseded.family, (
                    f"{a.code} (famiglia {a.family}) supersedes "
                    f"{a.supersedes} (famiglia {superseded.family})"
                )


class TestAchievementByMetricThresholds:
    """In BY_METRIC, le soglie di ciascuna metrica sono in ordine crescente.

    Questo garantisce che il motore possa scorrerle sequenzialmente e
    sbloccare più achievement nella stessa passata.
    """

    def test_thresholds_strictly_increasing_per_metric(self):
        """Verifica che per ogni metrica, thresholds siano strettamente crescenti."""
        for metric, achievements in R.BY_METRIC.items():
            thresholds = [a.threshold for a in achievements]
            for i in range(len(thresholds) - 1):
                assert thresholds[i] < thresholds[i + 1], (
                    f"Metrica '{metric}': thresholds non crescenti "
                    f"{thresholds[i]} >= {thresholds[i + 1]}"
                )


class TestAchievementFamilies:
    """Ogni famiglia usata in ACHIEVEMENTS deve avere un titolo in FAMILY_TITLES."""

    def test_all_families_have_titles(self):
        """Verifica che ogni famiglia usata sia in FAMILY_TITLES."""
        families_used = {a.family for a in R.ACHIEVEMENTS}
        for family in families_used:
            assert family in R.FAMILY_TITLES, (
                f"Famiglia '{family}' usata ma non in FAMILY_TITLES"
            )

    def test_family_titles_have_both_languages(self):
        """Verifica che ogni titolo famiglia abbia 'it' e 'en'."""
        for family, titles in R.FAMILY_TITLES.items():
            assert "it" in titles, f"FAMILY_TITLES[{family}]: manca italiano"
            assert "en" in titles, f"FAMILY_TITLES[{family}]: manca inglese"


class TestAchievementBackendsAndPlans:
    """backends e plans non sono mai vuoti e contengono solo valori validi."""

    def test_backends_never_empty_and_valid(self):
        """Verifica che backends non sia vuoto e contenga solo backend validi."""
        for a in R.ACHIEVEMENTS:
            assert len(a.backends) > 0, f"{a.code}: backends vuoto"
            for backend in a.backends:
                assert backend in R.ALL_BACKENDS, (
                    f"{a.code}: backend '{backend}' non valido"
                )

    def test_plans_never_empty_and_valid(self):
        """Verifica che plans non sia vuoto e contenga solo piani validi."""
        for a in R.ACHIEVEMENTS:
            assert len(a.plans) > 0, f"{a.code}: plans vuoto"
            for plan in a.plans:
                assert plan in R.ALL_PLANS, (
                    f"{a.code}: plan '{plan}' non valido"
                )


class TestAchievementIsAvailable:
    """is_available() correttamente controlla backend e piano."""

    def test_available_when_backend_and_plan_match(self):
        """Verifica che is_available() ritorni True se backend e plan sono inclusi."""
        # Crea un achievement di prova con backends/plans ristretti
        ach = R.AchievementDef(
            code="test_available",
            family="test",
            xp=10,
            icon="test",
            titles={"it": "Test", "en": "Test"},
            descriptions={"it": "Test", "en": "Test"},
            backends=("postgres",),
            plans=("pro",),
        )
        assert ach.is_available("postgres", "pro") is True
        assert ach.is_available("postgres", "free") is False
        assert ach.is_available("notion", "pro") is False
        assert ach.is_available("notion", "free") is False

    def test_goals_only_available_for_postgres_pro(self):
        """Verifica che goal_reached e goals_completed non siano disponibili
        per notion o free, come da regola del design.
        """
        goal_codes = [a.code for a in R.ACHIEVEMENTS if a.family == R.FAMILY_GOALS]
        assert len(goal_codes) > 0, "Nessun achievement goals trovato"
        for code in goal_codes:
            ach = R.BY_CODE[code]
            assert ach.backends == ("postgres",), (
                f"{code}: goals deve essere postgres-only"
            )
            assert ach.plans == ("pro",), (
                f"{code}: goals deve essere pro-only"
            )


class TestAchievementTitleAndDescriptionFallback:
    """title() e description() ripiegano sull'italiano per linguaggi sconosciuti."""

    def test_title_fallback_to_italian(self):
        """Verifica che title(locale_sconosciuta) ritorni l'italiano."""
        a = R.BY_CODE["volume_expenses_25"]  # Un achievement garantito
        assert a.title("it") == a.titles["it"]
        assert a.title("en") == a.titles["en"]
        assert a.title("fr") == a.titles["it"], (
            "title('fr') deve tornare all'italiano"
        )
        assert a.title("unknown") == a.titles["it"]

    def test_description_fallback_to_italian(self):
        """Verifica che description(locale_sconosciuta) ritorni l'italiano."""
        a = R.BY_CODE["volume_expenses_25"]
        assert a.description("it") == a.descriptions["it"]
        assert a.description("en") == a.descriptions["en"]
        assert a.description("fr") == a.descriptions["it"]
        assert a.description("unknown") == a.descriptions["it"]


class TestAchievementXPProgression:
    """Dentro la stessa metrica, achievement con threshold maggiore hanno XP ≥.

    Questo garantisce che la progressione verso traguardi più alti sia sempre
    remunerante, altrimenti l'utente potrebbe perdere XP sbloccando un tier
    successivo.
    """

    def test_xp_increases_with_threshold_per_metric(self):
        """Verifica che xp cresca (o resti uguale) con il threshold in ogni metrica."""
        for metric, achievements in R.BY_METRIC.items():
            for i in range(len(achievements) - 1):
                curr = achievements[i]
                next_ach = achievements[i + 1]
                assert curr.xp <= next_ach.xp, (
                    f"Metrica '{metric}': {curr.code} (xp={curr.xp}, "
                    f"threshold={curr.threshold}) > "
                    f"{next_ach.code} (xp={next_ach.xp}, "
                    f"threshold={next_ach.threshold})"
                )
