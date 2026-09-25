from datetime import date

from portafolio.core.calendario import (
    ZONA_BOGOTA,
    ahora_bogota,
    es_dia_habil,
    es_festivo,
    siguiente_dia_habil,
    sumar_dias_habiles,
)


def test_zona_horaria():
    assert ahora_bogota().tzinfo == ZONA_BOGOTA
    assert ahora_bogota().utcoffset().total_seconds() == -5 * 3600


def test_ley_emiliani_traslada_reyes_al_lunes():
    # 6 de enero de 2026 es martes: el festivo pasa al lunes 12.
    assert not es_festivo(date(2026, 1, 6))
    assert es_festivo(date(2026, 1, 12))


def test_festivos_fijos():
    assert es_festivo(date(2026, 1, 1))
    assert es_festivo(date(2025, 7, 20))
    assert es_festivo(date(2025, 12, 25))


def test_dia_habil():
    assert es_dia_habil(date(2026, 1, 13))
    assert not es_dia_habil(date(2026, 1, 10))  # sábado
    assert not es_dia_habil(date(2026, 1, 12))  # festivo


def test_siguiente_dia_habil():
    # Sábado 10 -> domingo -> lunes festivo 12 -> martes 13.
    assert siguiente_dia_habil(date(2026, 1, 10)) == date(2026, 1, 13)
    assert siguiente_dia_habil(date(2026, 1, 13)) == date(2026, 1, 13)


def test_sumar_dias_habiles():
    assert sumar_dias_habiles(date(2026, 1, 9), 1) == date(2026, 1, 13)
    assert sumar_dias_habiles(date(2026, 1, 13), -1) == date(2026, 1, 9)
    assert sumar_dias_habiles(date(2026, 1, 13), 0) == date(2026, 1, 13)
