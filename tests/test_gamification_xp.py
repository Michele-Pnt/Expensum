"""
tests/test_gamification_xp.py — Test puri per src/gamification/xp.py.

Nessun DB, nessun mock: verifica solo la curva di esperienza e la bidirezionalità
dei livelli. La curva quadratica chiusa cumulative_xp_for_level(L) = 50·L·(L−1)
deve essere strettamente crescente, invertibile via level_for_xp(), e produrre
uno stato di progress coerente via level_progress().
"""
import pytest

from src.gamification import xp

pytestmark = pytest.mark.unit


class TestCumulativeXPForLevel:
    """Verifica la formula della curva quadratica chiusa."""

    def test_level_1_requires_zero_xp(self):
        """Verifica che cumulative_xp_for_level(1) == 0 (livello 1 gratuito)."""
        assert xp.cumulative_xp_for_level(1) == 0

    def test_curve_strictly_increasing(self):
        """Verifica che la curva sia strettamente crescente da 2 a MAX_LEVEL.

        Nota: cumulative_xp_for_level(1) == 0 per design (livello 1 gratuito),
        quindi la crescita stretta inizia dal livello 2.
        """
        for level in range(2, xp.MAX_LEVEL + 1):
            previous_xp = xp.cumulative_xp_for_level(level - 1)
            current_xp = xp.cumulative_xp_for_level(level)
            assert current_xp > previous_xp, (
                f"Curva non strettamente crescente: "
                f"level {level} ({current_xp}) <= level {level - 1} ({previous_xp})"
            )

    def test_known_values(self):
        """Verifica alcuni valori noti della formula 50·L·(L−1)."""
        assert xp.cumulative_xp_for_level(1) == 0       # 50·1·0
        assert xp.cumulative_xp_for_level(2) == 100     # 50·2·1
        assert xp.cumulative_xp_for_level(3) == 300     # 50·3·2
        assert xp.cumulative_xp_for_level(4) == 600     # 50·4·3
        assert xp.cumulative_xp_for_level(5) == 1000    # 50·5·4

    def test_level_beyond_max_is_capped(self):
        """Verifica che cumulative_xp_for_level(>MAX_LEVEL) sia capped a MAX_LEVEL."""
        capped = xp.cumulative_xp_for_level(xp.MAX_LEVEL + 1)
        max_xp = xp.cumulative_xp_for_level(xp.MAX_LEVEL)
        assert capped == max_xp


class TestLevelForXP:
    """Verifica che level_for_xp sia l'inverso di cumulative_xp_for_level."""

    def test_inverse_relationship(self):
        """Verifica che level_for_xp(cumulative_xp_for_level(L)) == L
        per ogni livello da 1 a MAX_LEVEL.
        """
        for level in range(1, xp.MAX_LEVEL + 1):
            total_xp = xp.cumulative_xp_for_level(level)
            recovered_level = xp.level_for_xp(total_xp)
            assert recovered_level == level, (
                f"Inverso fallito: level_for_xp({total_xp}) = {recovered_level}, "
                f"atteso {level}"
            )

    def test_xp_just_below_threshold_gives_lower_level(self):
        """Verifica che XP appena sotto la soglia di L dia livello L-1."""
        for level in range(2, xp.MAX_LEVEL + 1):
            threshold = xp.cumulative_xp_for_level(level)
            below_threshold = threshold - 1
            result_level = xp.level_for_xp(below_threshold)
            assert result_level == level - 1, (
                f"Level {level} richiede {threshold} XP; "
                f"con {below_threshold} XP atteso livello {level - 1}, "
                f"ottenuto {result_level}"
            )

    def test_xp_at_threshold_gives_exact_level(self):
        """Verifica che XP esattamente alla soglia dia il livello corretto."""
        for level in range(2, xp.MAX_LEVEL + 1):
            threshold = xp.cumulative_xp_for_level(level)
            result_level = xp.level_for_xp(threshold)
            assert result_level == level, (
                f"XP {threshold} dovrebbe dare livello {level}, "
                f"ottenuto {result_level}"
            )

    def test_zero_and_negative_xp_give_level_1(self):
        """Verifica che XP <= 0 ritorni livello 1."""
        assert xp.level_for_xp(0) == 1
        assert xp.level_for_xp(-1) == 1
        assert xp.level_for_xp(-100) == 1

    def test_huge_xp_is_capped_at_max_level(self):
        """Verifica che XP enorme sia cappato a MAX_LEVEL."""
        result = xp.level_for_xp(10_000_000)
        assert result == xp.MAX_LEVEL


class TestLevelProgress:
    """Verifica lo stato completo di progress ritornato via level_progress()."""

    def test_zero_xp_gives_level_1_progress_zero(self):
        """Verifica che level_progress(0) ritorni livello 1 con progress_pct 0."""
        result = xp.level_progress(0)
        assert result["level"] == 1
        assert result["progress_pct"] == 0.0
        assert result["is_max"] is False

    def test_progress_pct_always_between_0_and_100(self):
        """Verifica che progress_pct sia sempre 0 <= pct <= 100 per un ampio range."""
        # Testa un campionamento di XP range(0, 50000, 137)
        test_points = list(range(0, 50000, 137))
        for total_xp in test_points:
            result = xp.level_progress(total_xp)
            pct = result["progress_pct"]
            assert 0.0 <= pct <= 100.0, (
                f"XP {total_xp}: progress_pct {pct} fuori range [0, 100]"
            )

    def test_xp_into_level_plus_xp_to_next_equals_xp_for_next(self):
        """Verifica che xp_into_level + xp_to_next == xp_for_next
        quando non si è al livello massimo.
        """
        test_points = list(range(0, 50000, 137))
        for total_xp in test_points:
            result = xp.level_progress(total_xp)
            if not result["is_max"]:
                xp_into = result["xp_into_level"]
                xp_to_next = result["xp_to_next"]
                xp_for_next = result["xp_for_next"]
                assert xp_into + xp_to_next == xp_for_next, (
                    f"XP {total_xp}: "
                    f"xp_into_level ({xp_into}) + xp_to_next ({xp_to_next}) "
                    f"!= xp_for_next ({xp_for_next})"
                )

    def test_max_level_state(self):
        """Verifica lo stato al livello massimo: is_max=True, xp_to_next=0,
        progress_pct=100.
        """
        max_xp = xp.cumulative_xp_for_level(xp.MAX_LEVEL)
        # Testa con XP esattamente alla soglia
        result = xp.level_progress(max_xp)
        assert result["level"] == xp.MAX_LEVEL
        assert result["is_max"] is True
        assert result["xp_to_next"] == 0
        assert result["progress_pct"] == 100.0

        # Testa con XP enormemente superiore
        result2 = xp.level_progress(max_xp + 10_000)
        assert result2["level"] == xp.MAX_LEVEL
        assert result2["is_max"] is True
        assert result2["xp_to_next"] == 0
        assert result2["progress_pct"] == 100.0

    def test_total_xp_preserved(self):
        """Verifica che level_progress() preservi total_xp in output."""
        for total_xp in [0, 100, 500, 1000, 50000]:
            result = xp.level_progress(total_xp)
            assert result["total_xp"] == max(0, total_xp), (
                f"total_xp {total_xp} non preservato in output"
            )

    def test_xp_into_level_consistency(self):
        """Verifica che xp_into_level sia sempre la differenza dalla soglia
        di livello corrente.
        """
        test_points = list(range(0, 10000, 247))
        for total_xp in test_points:
            result = xp.level_progress(total_xp)
            level = result["level"]
            floor_xp = xp.cumulative_xp_for_level(level)
            expected_into = max(0, total_xp - floor_xp)
            assert result["xp_into_level"] == expected_into, (
                f"XP {total_xp}, livello {level}: "
                f"xp_into_level {result['xp_into_level']} != atteso {expected_into}"
            )

    def test_is_max_flag_matches_level(self):
        """Verifica che is_max sia True solo quando level == MAX_LEVEL."""
        below_max = xp.cumulative_xp_for_level(xp.MAX_LEVEL - 1) + 50
        result_below = xp.level_progress(below_max)
        assert result_below["is_max"] is False

        at_max = xp.cumulative_xp_for_level(xp.MAX_LEVEL)
        result_at = xp.level_progress(at_max)
        assert result_at["is_max"] is True
