#!/bin/sh
set -eu

if [ "$(hostname)" = "transit-fw" ]; then
  nft -f /etc/nftables.conf
fi

if ip route show default | grep -q .; then
  ip route del default
fi

/usr/lib/frr/frrinit.sh start
exec tail -f /dev/null
