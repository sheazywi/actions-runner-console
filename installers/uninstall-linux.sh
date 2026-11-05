#!/usr/bin/env bash
set -euo pipefail
[[ $EUID == 0 ]] || { echo "Run as root." >&2; exit 1; }
install_dir=$(realpath "${1:-/opt/actions-runner-console}")
[[ -f $install_dir/config.json && -f $install_dir/run.py ]] || { echo "No installation found." >&2; exit 2; }
for manifest in "$install_dir"/getty-*.json; do
  [[ -f $manifest ]] || continue
  tty=${manifest##*/getty-}; tty=${tty%.json}
  [[ $tty =~ ^(tty[0-9]+|ttyS[0-9]+|hvc[0-9]+)$ ]] || exit 2
  systemctl disable --now "actions-runner-console-$tty.service"
  rm -f -- "/etc/systemd/system/actions-runner-console-$tty.service"
  read -r unit enabled active < <(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["unit"],d["enabled"],d["active"])' "$manifest")
  [[ $unit == "getty@$tty.service" || $unit == "serial-getty@$tty.service" ]] || exit 2
  if [[ $enabled != masked && $enabled != masked-runtime ]]; then
    systemctl unmask "$unit"
    [[ $enabled == enabled ]] && systemctl enable "$unit"
    [[ $active == active ]] && systemctl start "$unit"
  fi
done
systemctl disable --now actions-runner-console.service
rm -f -- /etc/systemd/system/actions-runner-console.service
python3 "$install_dir/run.py" --config "$install_dir/config.json" uninstall-hooks
systemctl daemon-reload
echo "Services removed and prior hooks restored. Restart the GitHub runner when idle."
echo "Program files and logs were kept at $install_dir and the configured data directory."
