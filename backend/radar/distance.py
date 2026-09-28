"""Estimativa de distância a partir do RSSI (modelo log-distance path loss).

    d = 10 ^ ((A - RSSI) / (10 * n))

Onde:
    A    = RSSI de referência (dBm) medido a 1 metro do AP
    n    = expoente de perda de percurso (path-loss exponent)
    RSSI = potência recebida filtrada (dBm, negativo)

A e n podem vir de calibração por BSSID; caso contrário usa-se o preset do
ambiente selecionado.
"""

# Expoente n típico por ambiente
ENV_N = {
    "indoor": 3.0,   # ambiente interno com paredes/obstáculos
    "urban": 2.7,    # área urbana / semi-aberta
    "open": 2.2,     # espaço aberto, quase linha de visada
}

DEFAULT_A = -40.0
DEFAULT_N = ENV_N["urban"]


def estimate_distance(rssi: float | None, a: float = DEFAULT_A, n: float = DEFAULT_N) -> float | None:
    if rssi is None:
        return None
    try:
        d = 10 ** ((a - rssi) / (10.0 * n))
    except (ValueError, OverflowError, ZeroDivisionError):
        return None
    if d != d or d in (float("inf"), float("-inf")):  # NaN/inf guard
        return None
    return round(d, 2)
