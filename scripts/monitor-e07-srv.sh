#!/bin/bash
# Live system summary of e07-srv for a tmux pane, like the first row of
# Grafana's Node Exporter "System" dashboard: CPU busy, system load
# (5 and 15 min, as % of cores), RAM, swap and root FS used, plus the
# cores, uptime and totals, and the GPU when nvidia-smi is present.
# Reads /proc only; no root needed.
#
#   scripts/monitor-e07-srv.sh [INTERVAL_S]     (default 5; Ctrl-C quits)

INTERVAL=${1:-5}
BAR_WIDTH=30
# Yellow / red thresholds (%), as the Grafana dashboard's gauges.
CPU_WARN=85; CPU_CRIT=95
LOAD_WARN=85; LOAD_CRIT=95
RAM_WARN=80; RAM_CRIT=90
SWAP_WARN=10; SWAP_CRIT=25
FS_WARN=80; FS_CRIT=90
GPU_WARN=85; GPU_CRIT=95
GIB=1048576  # KiB per GiB

GREEN=$'\e[32m'; YELLOW=$'\e[33m'; RED=$'\e[31m'
BOLD=$'\e[1m'; DIM=$'\e[2m'; RESET=$'\e[0m'

cleanup() { tput cnorm; echo; exit 0; }
trap cleanup INT TERM
tput civis

cpu_sample() {
  # Prints "busy total" jiffies from the aggregate cpu line.
  read -r _ user nice sys idle iowait irq softirq steal _ < /proc/stat
  local idle_all=$((idle + iowait))
  local total=$((user + nice + sys + idle + iowait + irq + softirq + steal))
  echo "$((total - idle_all)) $total"
}

# gauge LABEL PERCENT WARN CRIT [NOTE]
gauge() {
  local pct=$2 warn=$3 crit=$4 color=$GREEN
  local n=$(awk -v p="$pct" -v w=$BAR_WIDTH \
    'BEGIN { n = int(p * w / 100 + 0.5); print (n > w ? w : n) }')
  if awk -v p="$pct" -v c="$crit" 'BEGIN { exit !(p >= c) }'; then
    color=$RED
  elif awk -v p="$pct" -v c="$warn" 'BEGIN { exit !(p >= c) }'; then
    color=$YELLOW
  fi
  local bar=""
  for ((i = 0; i < BAR_WIDTH; i++)); do
    if ((i < n)); then bar+="█"; else bar+="·"; fi
  done
  printf "%-14s %s%s%s %s%6.1f%%%s  %s\e[K\n" "$1" "$color" "$bar" "$RESET" \
    "$color" "$pct" "$RESET" "$5"
}

meminfo() { awk -v k="$1:" '$1 == k { print $2 }' /proc/meminfo; }

pct() {
  awk -v a="$1" -v b="$2" 'BEGIN { printf "%.1f", (b > 0 ? 100 * a / b : 0) }'
}

gib() { awk -v k="$1" -v g=$GIB 'BEGIN { printf "%.1f GiB", k / g }'; }

uptime_str() {
  local s=$(cut -d. -f1 /proc/uptime)
  printf "%dd %02dh %02dm" $((s / 86400)) $((s % 86400 / 3600)) \
    $((s % 3600 / 60))
}

read -r prev_busy prev_total <<< "$(cpu_sample)"
sleep 1
clear
while true; do
  read -r busy total <<< "$(cpu_sample)"
  cpu=$(pct $((busy - prev_busy)) $((total - prev_total)))
  prev_busy=$busy; prev_total=$total

  cores=$(nproc)
  read -r load1 load5 load15 _ < /proc/loadavg
  mem_total=$(meminfo MemTotal)
  mem_used=$((mem_total - $(meminfo MemAvailable)))
  swap_total=$(meminfo SwapTotal)
  swap_used=$((swap_total - $(meminfo SwapFree)))
  read -r fs_total fs_used <<< "$(df -Pk / | awk 'NR == 2 { print $2, $3 }')"

  tput cup 0 0
  printf "%s%s%s  %s%s%s\e[K\n\e[K\n" "$BOLD" "$(hostname)" "$RESET" \
    "$DIM" "$(date '+%Y-%m-%d %H:%M:%S')  every ${INTERVAL}s" "$RESET"
  gauge "CPU Busy" "$cpu" $CPU_WARN $CPU_CRIT
  gauge "Sys Load 5m" "$(pct "$load5" "$cores")" $LOAD_WARN $LOAD_CRIT \
    "load $load1 / $load5 / $load15"
  gauge "Sys Load 15m" "$(pct "$load15" "$cores")" $LOAD_WARN $LOAD_CRIT
  gauge "RAM Used" "$(pct $mem_used "$mem_total")" $RAM_WARN $RAM_CRIT \
    "$(gib $mem_used) / $(gib "$mem_total")"
  gauge "SWAP Used" "$(pct $swap_used "$swap_total")" $SWAP_WARN \
    $SWAP_CRIT "$(gib $swap_used) / $(gib "$swap_total")"
  gauge "Root FS Used" "$(pct "$fs_used" "$fs_total")" $FS_WARN $FS_CRIT \
    "$(gib "$fs_used") / $(gib "$fs_total")"
  if command -v nvidia-smi > /dev/null; then
    nvidia-smi --query-gpu=index,utilization.gpu,memory.used,\
memory.total,temperature.gpu --format=csv,noheader,nounits |
    while IFS=', ' read -r idx util mused mtotal temp; do
      gauge "GPU$idx Util" "$util" $GPU_WARN $GPU_CRIT "${temp}°C"
      gauge "GPU$idx Mem" "$(pct "$mused" "$mtotal")" $GPU_WARN \
        $GPU_CRIT "$mused / $mtotal MiB"
    done
  fi
  printf "\n%-14s %d   %-8s %s\e[K\n" "CPU Cores" "$cores" "Uptime" \
    "$(uptime_str)"
  tput ed
  sleep "$INTERVAL"
done
