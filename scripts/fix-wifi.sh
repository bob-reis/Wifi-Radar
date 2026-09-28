#!/usr/bin/env bash
# fix-wifi.sh — recuperação de emergência do WiFi
# Alvo: notebook com WiFi interna Broadcom (driver wl) + adaptador USB Alfa (rt2800usb)
# Uso:  sudo bash fix-wifi.sh
#
# O que faz, em ordem:
#   1. para o scanner (container + airodump remanescente)
#   2. limpa rfkill (soft/hard block)
#   3. recarrega o driver Broadcom (costuma destravar o hard block)
#   4. devolve wlan0/wlan1 para managed e ao controle do NetworkManager
#   5. liga o rádio, reinicia o NetworkManager e reconecta a wlan0
#   6. (opcional) desliga o power-save da wlan0, que causa quedas
set +e

log() { printf '\033[1;32m[*]\033[0m %s\n' "$*"; }

log "Parando scanner (container wifi-radar) e airodump remanescente..."
docker stop wifi-radar 2>/dev/null
pkill -9 airodump-ng 2>/dev/null

log "Parando NetworkManager (libera o driver p/ recarregar)..."
systemctl stop NetworkManager 2>/dev/null

log "Apagando estado salvo do rfkill (senão o bloqueio volta no boot)..."
rm -f /var/lib/systemd/rfkill/* 2>/dev/null

log "Limpando rfkill (soft + hard block)..."
rfkill unblock all 2>/dev/null
rfkill unblock wifi 2>/dev/null

log "Recarregando driver Broadcom (wl)... (destrava hard block travado)"
modprobe -r wl 2>/dev/null
if lsmod | grep -q '^wl'; then
  log "  wl ainda carregado; forçando rmmod..."
  rmmod -f wl 2>/dev/null
fi
sleep 1
modprobe wl 2>/dev/null
sleep 1

log "Reiniciando NetworkManager..."
systemctl start NetworkManager 2>/dev/null
sleep 1

log "Devolvendo interfaces a managed + NetworkManager..."
for IF in wlan0 wlan1; do
  ip link set "$IF" down 2>/dev/null
  iw dev "$IF" set type managed 2>/dev/null
  ip link set "$IF" up 2>/dev/null
  nmcli device set "$IF" managed yes 2>/dev/null
done

log "Ligando rádio e reiniciando NetworkManager..."
nmcli radio all on 2>/dev/null
systemctl restart NetworkManager 2>/dev/null
sleep 2

log "Reconectando wlan0..."
nmcli device connect wlan0 2>/dev/null
sleep 3

# Prevenção: power-save da wlan0 costuma derrubar o link (Broadcom)
log "Desligando power-save da wlan0 (prevenção de quedas)..."
iw dev wlan0 set power_save off 2>/dev/null
iwconfig wlan0 power off 2>/dev/null

echo
echo "================ ESTADO ================"
echo "--- rfkill ---";        rfkill list 2>/dev/null | grep -E "Wireless|blocked"
echo "--- interfaces ---";    iw dev 2>/dev/null | grep -E "Interface|type"
echo "--- rota default ---";  ip route show default 2>/dev/null
echo "========================================"
if ip route show default 2>/dev/null | grep -q wlan0; then
  echo -e "\033[1;32m[✔] Rede OK: rota default via wlan0. SSH deve voltar.\033[0m"
else
  echo -e "\033[1;33m[!] Sem rota default via wlan0 ainda. Se persistir, faça: reboot\033[0m"
fi
