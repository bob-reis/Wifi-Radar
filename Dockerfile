FROM python:3.12-slim

# Ferramentas de rede/WiFi necessárias para scan real (monitor mode).
# O driver WiFi roda no kernel do HOST (compartilhado com o container);
# por isso o container precisa de --privileged e --network host.
RUN apt-get update && apt-get install -y --no-install-recommends \
        aircrack-ng \
        iw \
        iproute2 \
        ethtool \
        wireless-regdb \
        procps \
        kmod \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

ENV RADAR_DATA=/app/data
EXPOSE 8000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
