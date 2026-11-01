#!/usr/bin/env bash
# Preparacao de host: nao instala carteira, nao transfere BTC, nao expõe RPC.
set -Eeuo pipefail

diagnostico() {
  echo '=== Cartorio Bitcoin: recursos (sem segredos) ==='
  echo "SO e arquitetura: $(uname -s) $(uname -m)"
  if [[ -r /etc/os-release ]]; then
    . /etc/os-release
    echo "Distribuicao: ${PRETTY_NAME:-indefinida}"
  fi
  if [[ -r /proc/meminfo ]]; then
    awk '/^MemTotal:/{print "RAM total (GiB):", $2/1048576}' /proc/meminfo
  fi
  echo 'Disco do sistema:'
  df -h -P /
  if [[ -d /var/lib/bitcoind ]]; then
    echo 'Disco dos dados Bitcoin:'
    df -h -P /var/lib/bitcoind
  else
    echo 'Diretorio /var/lib/bitcoind ainda nao existe.'
  fi
  echo 'Ferramentas:'
  for name in python3 git tor bitcoind bitcoin-cli lightningd lightning-cli systemctl; do
    if command -v "$name" >/dev/null 2>&1; then
      echo "$name: disponivel"
    else
      echo "$name: ausente"
    fi
  done
  echo 'Este comando nao testa backup, saldo, rede ou sincronizacao.'
  echo 'Nunca compartilhe seed, Rune, senhas ou cookie RPC.'
}

preparar_base() {
  if [[ "$(id -u)" != 0 ]]; then
    echo 'Execute a preparacao com sudo.' >&2
    exit 2
  fi
  if [[ "$(uname -s)" != Linux || ! -r /etc/os-release ]]; then
    echo 'Somente Linux Debian ou Ubuntu.' >&2
    exit 2
  fi
  . /etc/os-release
  case "${ID:-}" in
    debian|ubuntu) ;;
    *) echo 'Sistema nao suportado, sem alteracoes.' >&2; exit 2 ;;
  esac
  command -v apt-get >/dev/null || { echo 'apt-get nao encontrado.' >&2; exit 2; }
  echo 'Instalando SOMENTE dependencias basicas e Tor.'
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y --no-install-recommends ca-certificates curl gnupg git jq python3 python3-venv python3-pip tor
  if ! id -u cartorio >/dev/null 2>&1; then
    useradd --system --create-home --home-dir /var/lib/cartorio --shell /usr/sbin/nologin cartorio
  fi
  install -d -m 0755 -o root -g root /opt/cartorio
  install -d -m 0750 -o root -g cartorio /etc/cartorio
  install -d -m 0700 -o cartorio -g cartorio /srv/cartorio/data
  install -d -m 0700 -o cartorio -g cartorio /srv/cartorio-backups
  echo 'Base instalada. Bitcoind/Lightning NAO instalados ou iniciados.'
  echo 'Nenhum pagamento, fatura, canal ou chave foi criado.'
}

case "${1:---diagnostico}" in
  --diagnostico)
    [[ "$#" -le 1 ]] || exit 2
    diagnostico
    ;;
  --preparar-base)
    [[ "$#" -eq 1 ]] || exit 2
    preparar_base
    ;;
  --help|-h)
    echo 'Uso: bash deploy/sem-cartao/preparar-servidor.sh [--diagnostico|--preparar-base]'
    ;;
  *)
    echo 'Argumento desconhecido. Use --help.' >&2
    exit 2
    ;;
esac
