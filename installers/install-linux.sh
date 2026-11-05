#!/usr/bin/env bash
set -euo pipefail
runner="" user="" install_dir=/opt/actions-runner-console data_dir=/var/lib/actions-runner-console
replace=() ttys=() takeover=0 restart=0
while (($#)); do
  case "$1" in
    --runner-dir) runner=$2; shift 2;;
    --user) user=$2; shift 2;;
    --install-dir) install_dir=$2; shift 2;;
    --data-dir) data_dir=$2; shift 2;;
    --tty) ttys+=("$2"); shift 2;;
    --take-over-console) takeover=1; shift;;
    --replace-hooks) replace=(--replace-hooks); shift;;
    --restart-runner) restart=1; shift;;
    *) echo "Unknown argument: $1" >&2; exit 2;;
  esac
done
[[ $EUID == 0 ]] || { echo "Run the installer as root; services run as the runner account." >&2; exit 1; }
[[ -n $runner && -n $user ]] || { echo "Required: --runner-dir /path/to/actions-runner --user runner" >&2; exit 2; }
[[ $(id -u "$user") != 0 ]] || { echo "Choose a non-root runner account." >&2; exit 2; }
python=$(command -v python3)
"$python" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ required"'
runner=$(realpath "$runner"); install_dir=$(realpath -m "$install_dir"); data_dir=$(realpath -m "$data_dir")
[[ -d $runner/_diag && $install_dir != / && $data_dir != / ]] || { echo "Invalid runner/install/data directory." >&2; exit 2; }
case "$data_dir/" in "$runner/"*|"$install_dir/"*) echo "Data must live outside the runner and program directories." >&2; exit 2;; esac
for path in "$install_dir" "$data_dir"; do
  [[ $path != *'%'* && $path != *'$'* && $path != *'"'* && $path != *$'\n'* && $path != *$'\r'* ]] || { echo "Unsupported unit-file path characters." >&2; exit 2; }
done
if (("${#ttys[@]}" > 0 && !takeover)); then echo "--tty requires explicit --take-over-console (replaces the selected login console)." >&2; exit 2; fi
for tty in "${ttys[@]}"; do [[ $tty =~ ^(tty[0-9]+|ttyS[0-9]+|hvc[0-9]+)$ ]] || { echo "Invalid TTY: $tty" >&2; exit 2; }; done
source_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
[[ $install_dir != "$source_dir" ]] || { echo "Install into a separate directory." >&2; exit 2; }
group=$(id -gn "$user")
install -d -m 755 "$install_dir/runner_console"
for file in "$source_dir"/runner_console/*.py; do install -m 644 "$file" "$install_dir/runner_console/"; done
install -m 644 "$source_dir/run.py" "$install_dir/run.py"
install -d -m 750 -o "$user" -g "$group" "$data_dir"
"$python" - "$runner" "$data_dir" "$install_dir/config.json" <<'PY'
import json,sys,pathlib
pathlib.Path(sys.argv[3]).write_text(json.dumps(dict(runner_dir=sys.argv[1],data_dir=sys.argv[2])),encoding="utf-8")
PY
"$python" "$install_dir/run.py" --config "$install_dir/config.json" install-hooks "${replace[@]}"
chown "$user:$group" "$data_dir/hooks-before.json"; chmod 600 "$data_dir/hooks-before.json"
cat > /etc/systemd/system/actions-runner-console.service <<UNIT
[Unit]
Description=GitHub Actions runner console collector
After=network.target
[Service]
User=$user
Group=$group
ExecStart="$python" "$install_dir/run.py" --config "$install_dir/config.json" collect
Restart=on-failure
RestartSec=2
UMask=0027
[Install]
WantedBy=multi-user.target
UNIT
for tty in "${ttys[@]}"; do
  getty="getty@$tty.service"; [[ $tty == ttyS* || $tty == hvc* ]] && getty="serial-getty@$tty.service"
  manifest="$install_dir/getty-$tty.json"
  if [[ ! -e $manifest ]]; then
    enabled=$(systemctl is-enabled "$getty" 2>/dev/null || true)
    active=$(systemctl is-active "$getty" 2>/dev/null || true)
    "$python" - "$manifest" "$getty" "$enabled" "$active" <<'PY'
import json,pathlib,sys
pathlib.Path(sys.argv[1]).write_text(json.dumps(dict(unit=sys.argv[2],enabled=sys.argv[3],active=sys.argv[4])))
PY
  fi
  systemctl mask --now "$getty"
  cat > "/etc/systemd/system/actions-runner-console-$tty.service" <<UNIT
[Unit]
Description=GitHub Actions runner dashboard on $tty
After=actions-runner-console.service
Conflicts=$getty
[Service]
User=$user
Group=$group
Environment=TERM=linux
ExecStart="$python" "$install_dir/run.py" --config "$install_dir/config.json" show
StandardInput=tty
StandardOutput=tty
StandardError=journal
TTYPath=/dev/$tty
TTYReset=yes
TTYVHangup=yes
Restart=always
RestartSec=2
[Install]
WantedBy=multi-user.target
UNIT
done
systemctl daemon-reload
systemctl enable --now actions-runner-console.service
for tty in "${ttys[@]}"; do systemctl enable --now "actions-runner-console-$tty.service"; done
if ((restart)); then
  service=$(cat "$runner/.service")
  systemctl restart "$service"
else
  echo "Restart the GitHub runner service when it is idle to load the job hooks."
fi
echo "Installed. Manual dashboard: $python $install_dir/run.py --config $install_dir/config.json show"
