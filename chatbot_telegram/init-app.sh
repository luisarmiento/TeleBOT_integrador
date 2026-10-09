#!/bin/sh
set -eu
psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -v ON_ERROR_STOP=1 \
  -v app_password="$DB_APP_PASSWORD" -f /opt/telebot/provision.sql
