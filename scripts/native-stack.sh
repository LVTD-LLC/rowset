#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${ROWSET_NATIVE_STATE_DIR:-$ROOT/.rowset-local}"
LOG_DIR="$STATE_DIR/logs"
RUN_DIR="$STATE_DIR/run"
PGDATA="$STATE_DIR/postgres"
REDIS_DATA="$STATE_DIR/redis"
CONFIG_FILE="$STATE_DIR/native-config"

if [[ -f "$CONFIG_FILE" ]]; then
  while IFS="=" read -r config_key config_value; do
    case "$config_key" in
      ROWSET_NATIVE_HOST) : "${ROWSET_NATIVE_HOST:=$config_value}" ;;
      ROWSET_NATIVE_PORT) : "${ROWSET_NATIVE_PORT:=$config_value}" ;;
      ROWSET_NATIVE_POSTGRES_PORT) : "${ROWSET_NATIVE_POSTGRES_PORT:=$config_value}" ;;
      ROWSET_NATIVE_POSTGRES_DB) : "${ROWSET_NATIVE_POSTGRES_DB:=$config_value}" ;;
      ROWSET_NATIVE_POSTGRES_USER) : "${ROWSET_NATIVE_POSTGRES_USER:=$config_value}" ;;
      ROWSET_NATIVE_POSTGRES_PASSWORD) : "${ROWSET_NATIVE_POSTGRES_PASSWORD:=$config_value}" ;;
      ROWSET_NATIVE_REDIS_PORT) : "${ROWSET_NATIVE_REDIS_PORT:=$config_value}" ;;
      ROWSET_NATIVE_REDIS_PASSWORD) : "${ROWSET_NATIVE_REDIS_PASSWORD:=$config_value}" ;;
      ROWSET_NATIVE_SMTP_PORT) : "${ROWSET_NATIVE_SMTP_PORT:=$config_value}" ;;
      ROWSET_NATIVE_MAIL_UI_PORT) : "${ROWSET_NATIVE_MAIL_UI_PORT:=$config_value}" ;;
    esac
  done < "$CONFIG_FILE"
fi

APP_HOST="${ROWSET_NATIVE_HOST:-127.0.0.1}"
APP_PORT="${ROWSET_NATIVE_PORT:-8000}"
POSTGRES_PORT="${ROWSET_NATIVE_POSTGRES_PORT:-5432}"
POSTGRES_DB="${ROWSET_NATIVE_POSTGRES_DB:-rowset}"
POSTGRES_USER="${ROWSET_NATIVE_POSTGRES_USER:-rowset}"
POSTGRES_PASSWORD="${ROWSET_NATIVE_POSTGRES_PASSWORD:-rowset}"
REDIS_PORT="${ROWSET_NATIVE_REDIS_PORT:-6379}"
REDIS_PASSWORD="${ROWSET_NATIVE_REDIS_PASSWORD:-rowset}"
MAILPIT_SMTP_PORT="${ROWSET_NATIVE_SMTP_PORT:-1025}"
MAILPIT_UI_PORT="${ROWSET_NATIVE_MAIL_UI_PORT:-8025}"

cd "$ROOT"

# Homebrew's keg-only libpq can shadow the full PostgreSQL installation. Prefer
# the PostgreSQL 18 keg when it is available so initdb can locate `postgres`.
if command -v brew >/dev/null 2>&1; then
  homebrew_postgres_bin="$(brew --prefix postgresql@18 2>/dev/null || true)/bin"
  if [[ -x "$homebrew_postgres_bin/postgres" ]]; then
    export PATH="$homebrew_postgres_bin:$PATH"
  fi
fi

info() {
  printf "\n==> %s\n" "$1"
}

die() {
  printf "native-stack: %s\n" "$1" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Usage: ./scripts/native-stack.sh <command>

Commands:
  setup    Install Python and Node dependencies and build frontend assets
  start    Start Postgres, Redis, Mailpit, frontend, workers, and Django
  stop     Stop every Rowset native service
  restart  Stop and start every Rowset native service
  status   Show service status and local URLs
  logs     Follow logs for all services (or pass one service name)
  manage   Run a Django management command against the native stack
  test     Run pytest against the native stack

Configuration:
  ROWSET_NATIVE_PORT=8010             Django port (default: 8000)
  ROWSET_NATIVE_POSTGRES_PORT=55432   Postgres port (default: 5432)
  ROWSET_NATIVE_REDIS_PORT=56379      Redis port (default: 6379)
  ROWSET_NATIVE_SMTP_PORT=11025       Mailpit SMTP port (default: 1025)
  ROWSET_NATIVE_MAIL_UI_PORT=18025    Mailpit UI port (default: 8025)
  ROWSET_NATIVE_STRIPE=1              Also run Stripe webhook forwarding
EOF
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "$1 is required. $2"
}

ensure_directories() {
  mkdir -p "$LOG_DIR" "$RUN_DIR" "$REDIS_DATA"
}

ensure_env() {
  if [[ ! -f .env ]]; then
    cp .env.example .env
    info "Created .env from .env.example"
  fi
}

validate_identifier() {
  [[ "$1" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || die "$2 must be a PostgreSQL identifier"
}

validate_port() {
  [[ "$1" =~ ^[0-9]+$ ]] && (( 1 <= 10#$1 && 10#$1 <= 65535 )) \
    || die "$2 must be a port between 1 and 65535"
}

save_native_config() {
  umask 077
  {
    printf "ROWSET_NATIVE_HOST=%s\n" "$APP_HOST"
    printf "ROWSET_NATIVE_PORT=%s\n" "$APP_PORT"
    printf "ROWSET_NATIVE_POSTGRES_PORT=%s\n" "$POSTGRES_PORT"
    printf "ROWSET_NATIVE_POSTGRES_DB=%s\n" "$POSTGRES_DB"
    printf "ROWSET_NATIVE_POSTGRES_USER=%s\n" "$POSTGRES_USER"
    printf "ROWSET_NATIVE_POSTGRES_PASSWORD=%s\n" "$POSTGRES_PASSWORD"
    printf "ROWSET_NATIVE_REDIS_PORT=%s\n" "$REDIS_PORT"
    printf "ROWSET_NATIVE_REDIS_PASSWORD=%s\n" "$REDIS_PASSWORD"
    printf "ROWSET_NATIVE_SMTP_PORT=%s\n" "$MAILPIT_SMTP_PORT"
    printf "ROWSET_NATIVE_MAIL_UI_PORT=%s\n" "$MAILPIT_UI_PORT"
  } > "$CONFIG_FILE"
}

check_prerequisites() {
  require_command uv "Install it from https://docs.astral.sh/uv/."
  require_command node "Install Node.js 24 or newer."
  require_command npm "Install npm 11 or newer."
  require_command initdb "Install PostgreSQL 18 (macOS: brew install postgresql@18)."
  require_command postgres "Install the PostgreSQL server (macOS: brew install postgresql@18)."
  require_command pg_ctl "Install PostgreSQL 18 (macOS: brew install postgresql@18)."
  require_command pg_isready "Install PostgreSQL 18 (macOS: brew install postgresql@18)."
  require_command pg_config "Install PostgreSQL 18 (macOS: brew install postgresql@18)."
  require_command psql "Install PostgreSQL 18 (macOS: brew install postgresql@18)."
  require_command createdb "Install PostgreSQL 18 (macOS: brew install postgresql@18)."
  require_command redis-server "Install Redis (macOS: brew install redis)."
  require_command redis-cli "Install Redis (macOS: brew install redis)."
  require_command mailpit "Install Mailpit (macOS: brew install mailpit)."
  validate_identifier "$POSTGRES_DB" "ROWSET_NATIVE_POSTGRES_DB"
  validate_identifier "$POSTGRES_USER" "ROWSET_NATIVE_POSTGRES_USER"
  validate_port "$APP_PORT" "ROWSET_NATIVE_PORT"
  validate_port "$POSTGRES_PORT" "ROWSET_NATIVE_POSTGRES_PORT"
  validate_port "$REDIS_PORT" "ROWSET_NATIVE_REDIS_PORT"
  validate_port "$MAILPIT_SMTP_PORT" "ROWSET_NATIVE_SMTP_PORT"
  validate_port "$MAILPIT_UI_PORT" "ROWSET_NATIVE_MAIL_UI_PORT"
  local postgres_sharedir
  postgres_sharedir="$(pg_config --sharedir)"
  [[ -f "$postgres_sharedir/extension/vector.control" ]] \
    || die "pgvector is required (macOS: brew install pgvector)."
}

setup() {
  check_prerequisites
  ensure_directories
  ensure_env

  info "Installing locked Python dependencies"
  uv sync --locked --all-groups

  info "Installing locked frontend dependencies"
  npm ci

  info "Building frontend assets"
  npm run build

  printf "\nNative dependencies are ready. Run: make native-start\n"
}

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(<"$pid_file")"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

port_in_use() {
  "$ROOT/.venv/bin/python" -c \
    'import socket, sys; s = socket.socket(); s.settimeout(0.2); sys.exit(s.connect_ex((sys.argv[1], int(sys.argv[2]))) != 0)' \
    "$1" "$2"
}

require_free_port() {
  local port="$1"
  local service="$2"
  if port_in_use 127.0.0.1 "$port"; then
    die "port $port is already in use by another process ($service). Override its ROWSET_NATIVE_*_PORT value."
  fi
}

preflight_start_ports() {
  if ! { [[ -f "$PGDATA/PG_VERSION" ]] && pg_ctl --pgdata="$PGDATA" status >/dev/null 2>&1; }; then
    require_free_port "$POSTGRES_PORT" "PostgreSQL"
  fi
  if ! is_running "$RUN_DIR/redis.pid"; then
    require_free_port "$REDIS_PORT" "Redis"
  fi
  if ! is_running "$RUN_DIR/mailpit.pid"; then
    require_free_port "$MAILPIT_SMTP_PORT" "Mailpit SMTP"
    require_free_port "$MAILPIT_UI_PORT" "Mailpit UI"
  fi
  if ! is_running "$RUN_DIR/backend.pid"; then
    require_free_port "$APP_PORT" "Django"
  fi
}

start_postgres() {
  if [[ ! -f "$PGDATA/PG_VERSION" ]]; then
    info "Initializing PostgreSQL data in $PGDATA"
    mkdir -p "$PGDATA"
    local password_file="$STATE_DIR/postgres-password"
    umask 077
    printf "%s\n" "$POSTGRES_PASSWORD" > "$password_file"
    if ! initdb \
      --pgdata="$PGDATA" \
      --username="$POSTGRES_USER" \
      --pwfile="$password_file" \
      --auth-local=trust \
      --auth-host=scram-sha-256 >/dev/null; then
      rm -f "$password_file"
      die "PostgreSQL initialization failed."
    fi
    rm -f "$password_file"
  fi

  if pg_ctl --pgdata="$PGDATA" status >/dev/null 2>&1; then
    printf "PostgreSQL is already running.\n"
  else
    require_free_port "$POSTGRES_PORT" "PostgreSQL"
    info "Starting PostgreSQL on 127.0.0.1:$POSTGRES_PORT"
    pg_ctl \
      --pgdata="$PGDATA" \
      --log="$LOG_DIR/postgres.log" \
      --options="-h 127.0.0.1 -p $POSTGRES_PORT -c shared_preload_libraries=pg_stat_statements" \
      start >/dev/null
  fi

  for _ in {1..30}; do
    if PGPASSWORD="$POSTGRES_PASSWORD" pg_isready \
      --host=127.0.0.1 --port="$POSTGRES_PORT" --username="$POSTGRES_USER" >/dev/null; then
      break
    fi
    sleep 1
  done

  PGPASSWORD="$POSTGRES_PASSWORD" pg_isready \
    --host=127.0.0.1 --port="$POSTGRES_PORT" --username="$POSTGRES_USER" >/dev/null \
    || die "PostgreSQL did not become ready. See $LOG_DIR/postgres.log."

  if ! PGPASSWORD="$POSTGRES_PASSWORD" psql \
    --host=127.0.0.1 \
    --port="$POSTGRES_PORT" \
    --username="$POSTGRES_USER" \
    --dbname=postgres \
    --tuples-only \
    --command="SELECT 1 FROM pg_database WHERE datname = '$POSTGRES_DB'" | grep -q 1; then
    info "Creating PostgreSQL database $POSTGRES_DB"
    PGPASSWORD="$POSTGRES_PASSWORD" createdb \
      --host=127.0.0.1 \
      --port="$POSTGRES_PORT" \
      --username="$POSTGRES_USER" \
      "$POSTGRES_DB"
  fi
}

start_redis() {
  local pid_file="$RUN_DIR/redis.pid"
  if is_running "$pid_file"; then
    printf "Redis is already running.\n"
    return
  fi

  rm -f "$pid_file"
  require_free_port "$REDIS_PORT" "Redis"
  info "Starting Redis on 127.0.0.1:$REDIS_PORT"
  redis-server \
    --bind 127.0.0.1 \
    --port "$REDIS_PORT" \
    --requirepass "$REDIS_PASSWORD" \
    --dir "$REDIS_DATA" \
    --appendonly yes \
    --daemonize yes \
    --pidfile "$pid_file" \
    --logfile "$LOG_DIR/redis.log"

  for _ in {1..30}; do
    if redis-cli -h 127.0.0.1 -p "$REDIS_PORT" -a "$REDIS_PASSWORD" \
      --no-auth-warning ping 2>/dev/null | grep -q PONG; then
      return
    fi
    sleep 1
  done
  die "Redis did not become ready. See $LOG_DIR/redis.log."
}

export_native_environment() {
  export POSTGRES_HOST=127.0.0.1
  export POSTGRES_PORT
  export POSTGRES_DB
  export POSTGRES_USER
  export POSTGRES_PASSWORD
  export REDIS_HOST=127.0.0.1
  export REDIS_PORT
  export REDIS_PASSWORD
  export EMAIL_HOST=127.0.0.1
  export EMAIL_PORT="$MAILPIT_SMTP_PORT"
  export MJML_BACKEND_MODE=cmd
  export MJML_EXEC_CMD="$ROOT/node_modules/.bin/mjml"
  export SITE_URL="${ROWSET_NATIVE_SITE_URL:-http://localhost:$APP_PORT}"
}

start_process() {
  local name="$1"
  shift
  local pid_file="$RUN_DIR/$name.pid"

  if is_running "$pid_file"; then
    printf "%s is already running (PID %s).\n" "$name" "$(<"$pid_file")"
    return
  fi

  rm -f "$pid_file"
  : > "$LOG_DIR/$name.log"
  nohup "$ROOT/.venv/bin/python" -c \
    'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' \
    "$@" >>"$LOG_DIR/$name.log" 2>&1 &
  local pid=$!
  printf "%s\n" "$pid" > "$pid_file"
  sleep 0.2

  if ! is_running "$pid_file"; then
    tail -n 30 "$LOG_DIR/$name.log" >&2 || true
    die "$name exited during startup."
  fi
  printf "Started %s (PID %s).\n" "$name" "$pid"
}

start_stripe_if_requested() {
  if [[ "${ROWSET_NATIVE_STRIPE:-0}" != "1" ]]; then
    return 0
  fi
  require_command stripe "Install Stripe CLI and run stripe login."
  start_process stripe stripe listen --forward-to "http://$APP_HOST:$APP_PORT/stripe/webhook/"
}

start() {
  check_prerequisites
  ensure_directories
  ensure_env
  save_native_config

  if [[ ! -x .venv/bin/python || ! -x node_modules/.bin/mjml ]]; then
    setup
  fi

  if [[ ! -f frontend/build/manifest.json ]]; then
    info "Building initial frontend assets"
    npm run build
  fi

  preflight_start_ports
  start_postgres
  start_redis
  export_native_environment

  info "Applying Django migrations"
  "$ROOT/.venv/bin/python" manage.py migrate --noinput

  if ! is_running "$RUN_DIR/mailpit.pid"; then
    require_free_port "$MAILPIT_SMTP_PORT" "Mailpit SMTP"
    require_free_port "$MAILPIT_UI_PORT" "Mailpit UI"
  fi
  start_process mailpit env \
    "MP_SMTP_BIND_ADDR=127.0.0.1:$MAILPIT_SMTP_PORT" \
    "MP_UI_BIND_ADDR=127.0.0.1:$MAILPIT_UI_PORT" \
    mailpit

  start_process frontend node scripts/build-assets.mjs --watch
  start_process workers env APP_PROCESS_TYPE=worker \
    "$ROOT/.venv/bin/python" manage.py qcluster

  if ! is_running "$RUN_DIR/backend.pid"; then
    require_free_port "$APP_PORT" "Django"
  fi
  start_process backend env APP_PROCESS_TYPE=server \
    "$ROOT/.venv/bin/python" manage.py runserver "$APP_HOST:$APP_PORT"
  start_stripe_if_requested

  for _ in {1..30}; do
    if port_in_use "$APP_HOST" "$APP_PORT"; then
      printf "\nRowset is ready at %s\n" "$SITE_URL"
      printf "Mailpit is ready at http://localhost:%s\n" "$MAILPIT_UI_PORT"
      printf "Logs: make native-logs    Stop: make native-stop\n"
      return
    fi
    sleep 1
  done

  tail -n 50 "$LOG_DIR/backend.log" >&2 || true
  die "Django did not become ready."
}

stop_process() {
  local name="$1"
  local pid_file="$RUN_DIR/$name.pid"
  if ! is_running "$pid_file"; then
    rm -f "$pid_file"
    printf "%s is stopped.\n" "$name"
    return
  fi

  local pid
  pid="$(<"$pid_file")"
  /bin/kill -TERM "-$pid" >/dev/null 2>&1 || kill -TERM "$pid" >/dev/null 2>&1 || true
  for _ in {1..30}; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      rm -f "$pid_file"
      printf "Stopped %s.\n" "$name"
      return
    fi
    sleep 0.2
  done
  /bin/kill -KILL "-$pid" >/dev/null 2>&1 || kill -KILL "$pid" >/dev/null 2>&1 || true
  rm -f "$pid_file"
  printf "Force-stopped %s.\n" "$name"
}

stop() {
  ensure_directories
  info "Stopping Rowset application processes"
  stop_process stripe
  stop_process backend
  stop_process workers
  stop_process frontend
  stop_process mailpit

  info "Stopping Redis"
  if is_running "$RUN_DIR/redis.pid"; then
    stop_process redis
  else
    rm -f "$RUN_DIR/redis.pid"
    printf "Redis is stopped.\n"
  fi

  info "Stopping PostgreSQL"
  if [[ -f "$PGDATA/PG_VERSION" ]] && pg_ctl --pgdata="$PGDATA" status >/dev/null 2>&1; then
    pg_ctl --pgdata="$PGDATA" stop --mode=fast >/dev/null
    printf "Stopped PostgreSQL.\n"
  else
    printf "PostgreSQL is stopped.\n"
  fi
}

print_process_status() {
  local name="$1"
  local pid_file="$RUN_DIR/$name.pid"
  if is_running "$pid_file"; then
    printf "%-12s running (PID %s)\n" "$name" "$(<"$pid_file")"
  else
    printf "%-12s stopped\n" "$name"
  fi
}

status() {
  ensure_directories
  printf "Native Rowset stack\n"
  if [[ -f "$PGDATA/PG_VERSION" ]] && pg_ctl --pgdata="$PGDATA" status >/dev/null 2>&1; then
    printf "%-12s running on 127.0.0.1:%s\n" "postgres" "$POSTGRES_PORT"
  else
    printf "%-12s stopped\n" "postgres"
  fi
  if is_running "$RUN_DIR/redis.pid"; then
    printf "%-12s running on 127.0.0.1:%s\n" "redis" "$REDIS_PORT"
  else
    printf "%-12s stopped\n" "redis"
  fi
  print_process_status mailpit
  print_process_status frontend
  print_process_status workers
  print_process_status backend
  if [[ -f "$RUN_DIR/stripe.pid" ]]; then
    print_process_status stripe
  fi
  printf "\nApp:     http://localhost:%s\n" "$APP_PORT"
  printf "Mailpit: http://localhost:%s\n" "$MAILPIT_UI_PORT"
  printf "Data:    %s\n" "$STATE_DIR"
  printf "Logs:    %s\n" "$LOG_DIR"
}

logs() {
  ensure_directories
  local service="${1:-}"
  if [[ -n "$service" ]]; then
    [[ -f "$LOG_DIR/$service.log" ]] || die "no log exists for $service"
    exec tail -n 100 -F "$LOG_DIR/$service.log"
  fi

  local log_files=("$LOG_DIR"/*.log)
  [[ -e "${log_files[0]}" ]] || die "no native service logs exist yet"
  exec tail -n 50 -F "${log_files[@]}"
}

prepare_native_command() {
  ensure_env
  [[ -x .venv/bin/python ]] || die "native dependencies are missing; run make native-setup"
  export_native_environment
}

manage_command() {
  prepare_native_command
  exec "$ROOT/.venv/bin/python" manage.py "$@"
}

test_command() {
  prepare_native_command
  exec "$ROOT/.venv/bin/pytest" "$@"
}

command="${1:-}"
shift || true
case "$command" in
  setup) setup ;;
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) status ;;
  logs) logs "${1:-}" ;;
  manage) manage_command "$@" ;;
  test) test_command "$@" ;;
  help|-h|--help) usage ;;
  *) usage; exit 1 ;;
esac
