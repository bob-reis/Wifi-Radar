# Wi-Fi Radar — Web Edition 📡

Versão **web + Docker** do *Hackers-Arise Wi-Fi Radar* (tool original de terminal
do Mike211). Descobre e mapeia access points Wi-Fi em tempo real usando só um
notebook Linux ou adaptador USB — sem GPS.

Reescreve o núcleo do tool original como um serviço web:

- **Scan contínuo** em 2.4 / 5 / 6 GHz (ou todas) via `airodump-ng`
- **Setup automático da interface**: monitor mode, domínio regulatório, TX power
- **Filtro de Kalman** por BSSID para suavizar o RSSI
- **Estimativa de distância** por modelo log-distance path loss
- **Calibração RSSI→distância** por AP (ajuste de A, n e R²), persistida
- **Radar visual** com layout *spring* (canvas), atualizado ao vivo por WebSocket
- **Focus mode**: trava e acompanha um único BSSID
- **Modo simulação**: exercita toda a UI/pipeline sem hardware

---

## ⚠️ Requisito de hardware: monitor mode

O scan real depende de **monitor mode** no adaptador. Placas com driver
**Broadcom `wl` (proprietário)** — comuns em notebooks — **não suportam** monitor
mode. Verifique com:

```bash
iw phy phy0 info | grep -A10 "Supported interface modes"
```

Se `monitor` não aparecer, use um **adaptador USB compatível** (Alfa AWUS036 com
chipset Atheros/Ralink/Realtek, etc.). Sem adaptador compatível, use o **modo
simulação** para explorar a interface.

### Validado em hardware real ✔

O scan real foi validado num notebook (Kali) com adaptador USB **Ralink RT3070
(`rt2800usb`)**: captura de APs ao vivo, filtragem Kalman, estimativa de
distância e o Focus/Stop funcionando — tudo com a interface de uplink do host
protegida (o SSH não caiu ao escanear por outro adaptador).

**Notas de campo sobre adaptadores:**
- **Nunca escaneie pela interface que dá internet ao host** — o app já esconde da
  lista as interfaces sem monitor e bloqueia a de uplink, mas fica o aviso.
- **Evite hubs USB sem fonte** — adaptadores como a RT3070 puxam corrente e, atrás
  de hub passivo, dão `error -71`/`hard block`/até kernel panic. Prefira **porta
  USB direta** ou **hub com fonte própria**.
- A **RT3070** funciona mas pode ser **intermitente** (desconecta sozinha após
  alguns minutos, é 2.4 GHz-only). Para uso sério, adaptadores mais estáveis:
  **Atheros AR9271** (`ath9k_htc`), **MT7601U**, **RTL8812AU** (dual-band).
- Em notebooks Apple/Broadcom (`wl`): a WiFi **interna não faz monitor mode** e
  ainda costuma carregar o SSH — use sempre um adaptador USB separado.
- Recuperação de emergência do WiFi do host: `sudo bash scripts/fix-wifi.sh`.

---

## 🚀 Rodando com Docker (recomendado)

```bash
docker compose up --build
```

Abra **http://localhost:8000**.

O container roda com `network_mode: host` + `privileged` + `pid: host` porque o
driver WiFi vive no kernel do host — é o que permite monitor mode de dentro do
container. Perfis de calibração ficam em `./data`.

**Segurança de conectividade:** o tool ativa monitor mode de forma *cirúrgica* —
tira apenas a interface escolhida do NetworkManager (`nmcli device set <if>
managed no`) e usa `iw`, **sem** `airmon-ng check kill`. Assim, se o host estiver
conectado por outra interface WiFi (ex.: `wlan0` gerenciada pelo NetworkManager),
essa conexão **não** cai. Escaneie sempre por um adaptador **diferente** do que
provê a rede do host.

## 🐍 Rodando sem Docker (dev / teste rápido)

```bash
pip install -r requirements.txt
# para scan real: apt install aircrack-ng iw iproute2 ethtool wireless-regdb
sudo -E uvicorn backend.app:app --host 0.0.0.0 --port 8000
```

`sudo` é necessário para monitor mode / `iw` / `airodump-ng`. Para só testar em
modo simulação, não precisa de root.

---

## Como usar

1. **Modo**: `Real` (precisa de interface + monitor mode) ou `Simulação`.
2. Escolha **interface**, **banda** e **ambiente** (define o expoente `n` inicial).
3. **▶ Iniciar** — o radar preenche com os APs; raio = distância estimada.
4. **Calibração**: selecione um AP, informe distâncias reais (com `⎗` captura o
   RSSI atual), some ≥2 amostras e **Ajustar & salvar**. APs calibrados ganham
   anel amarelo e passam a usar o próprio A/n.
5. **🎯 Focus**: clique no alvo na tabela para travar `airodump-ng` naquele BSSID.
6. **Sintonia & Regulatório**: aplica `iw reg set <país>` e TX power, e mostra o
   driver (`ethtool -i`).

---

## Modelo de distância

```
d = 10 ^ ((A - RSSI) / (10 * n))
```

- `A` = RSSI de referência a 1 m (dBm) — calibrável por AP
- `n` = expoente de path loss (indoor ≈ 3.0, urbano ≈ 2.7, aberto ≈ 2.2)

RSSI é filtrado por Kalman antes do cálculo. A distância é uma **estimativa**
(afetada por multipath, obstáculos, orientação da antena) — calibrar melhora
bastante.

---

## Arquitetura

```
backend/
  app.py            FastAPI: REST + WebSocket + orquestração do scan
  radar/
    scanner.py      airodump-ng wrapper (CSV) + simulador
    kalman.py       filtro de Kalman 1D por BSSID
    distance.py     modelo log-distance path loss
    calibration.py  ajuste de curva + persistência dos perfis
    iface.py        monitor mode / reg domain / txpower / driver
    state.py        estado dos APs + snapshot para o frontend
frontend/           UI (HTML/CSS/JS puro) — radar em canvas + WebSocket
```

## Uso ético

Ferramenta para **auditoria autorizada, pesquisa e educação**. Escaneamento
passivo de redes é regulado de forma diferente em cada país — use apenas em
redes próprias ou com autorização.
