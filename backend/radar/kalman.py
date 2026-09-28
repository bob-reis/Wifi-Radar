"""Filtro de Kalman 1D para suavização de RSSI por BSSID.

Modelo escalar: assume que o RSSI "real" varia lentamente (random walk),
enquanto a medição do adaptador tem ruído. Suaviza picos transientes e
produz uma média móvel adaptativa, melhorando a estimativa de distância.
"""


class KalmanRSSI:
    def __init__(self, R: float = 4.0, Q: float = 0.05, initial: float | None = None):
        # R: ruído de medição (dBm^2). Maior -> mais suave, responde devagar.
        # Q: ruído de processo. Maior -> segue mudanças reais mais rápido.
        self.R = R
        self.Q = Q
        self.P = 1000.0          # incerteza inicial (alta)
        self.x = initial          # estado estimado (RSSI filtrado)

    def update(self, measurement: float) -> float:
        if self.x is None:
            self.x = measurement
            self.P = self.R
            return self.x
        # Predição (A = H = 1)
        self.P += self.Q
        # Ganho de Kalman
        K = self.P / (self.P + self.R)
        # Correção
        self.x = self.x + K * (measurement - self.x)
        self.P = (1 - K) * self.P
        return self.x
