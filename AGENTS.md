# Security rules

- Never print, read, or include `.env` or `.secrets/` contents in tool output.
- Never run unfiltered `docker inspect`, `docker compose config`, `env`, `printenv`, or full-command `ps` on deployment services.
- Inspect only explicitly selected, non-secret fields such as container status and health.
- Keep the Cloudflare Tunnel token in `.secrets/cloudflare_tunnel_token` and pass it with `--token-file`.
- Request secrets through hidden interactive input. Never place them in chat, command arguments, shell history, logs, or Git.
