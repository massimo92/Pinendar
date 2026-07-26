#!/bin/sh
set -eu

pinendar migrate
exec "$@"

