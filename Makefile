# Makefile — friendly entry points for local SaaS staging.
#
# All targets are thin wrappers around scripts/dev/saas_staging.sh and
# scripts/dev/saas_tunnel.sh. The real logic lives there.
#
# Run `make help` (or just `make`) for the cheat sheet.

.PHONY: help saas-help saas-up saas-seed saas-test saas-status saas-urls \
        saas-logs saas-down saas-reset saas-nuke saas-tunnel-up \
        saas-tunnel-down saas-tunnel-test test up down

# Default — print the cheat sheet, do not start anything.
.DEFAULT_GOAL := help

help:
	@printf '\n'
	@printf '  \033[1mLocal SaaS staging — quick commands\033[0m\n'
	@printf '\n'
	@printf '  \033[1mEveryday flow:\033[0m\n'
	@printf '    \033[36mmake saas-up\033[0m         Build + start the stack (mongo, emulator, backend, frontend)\n'
	@printf '    \033[36mmake saas-seed\033[0m       Seed acme tenant + Firebase test user; print URLs + creds\n'
	@printf '    \033[36mmake saas-test\033[0m       Run the SaaS readiness smoke (7 gates)\n'
	@printf '    \033[36mmake saas-status\033[0m     Show containers + URLs + login credentials\n'
	@printf '    \033[36mmake saas-down\033[0m       Stop the stack (Mongo data preserved)\n'
	@printf '\n'
	@printf '  \033[1mShortcuts:\033[0m\n'
	@printf '    \033[36mmake up\033[0m              Alias: saas-up then saas-seed then saas-status\n'
	@printf '    \033[36mmake test\033[0m            Alias: saas-test\n'
	@printf '    \033[36mmake down\033[0m            Alias: saas-down\n'
	@printf '\n'
	@printf '  \033[1mPublic tunnels (Phase B):\033[0m\n'
	@printf '    \033[36mmake saas-tunnel-up\033[0m  Start cloudflared sidecars; print *.trycloudflare.com URLs\n'
	@printf '    \033[36mmake saas-tunnel-test\033[0m Re-run smoke against tunnel URLs\n'
	@printf '    \033[36mmake saas-tunnel-down\033[0m Stop tunnels only (base stack stays up)\n'
	@printf '\n'
	@printf '  \033[1mLess common:\033[0m\n'
	@printf '    \033[36mmake saas-urls\033[0m       Just print the access URLs\n'
	@printf '    \033[36mmake saas-logs SERVICE=backend\033[0m  Tail logs (default: backend)\n'
	@printf '    \033[36mmake saas-reset\033[0m      Wipe seeded test data, keep stack running\n'
	@printf '    \033[36mmake saas-nuke\033[0m       Stop + wipe everything (Mongo volume too) — needs confirm\n'
	@printf '\n'
	@printf '  See \033[36mdocs/runbooks/saas-local-staging.md\033[0m for the full runbook.\n'
	@printf '\n'

saas-help: help

# --- One-shot ---------------------------------------------------------------

# `make up` = bring the stack up, seed it, show the status. The full setup
# in a single command — what you want after `git clone` or `make saas-nuke`.
up: saas-up saas-seed saas-status

test: saas-test

down: saas-down

# --- Core stack -------------------------------------------------------------

saas-up:
	@scripts/dev/saas_staging.sh up

saas-seed:
	@scripts/dev/saas_staging.sh seed

saas-test:
	@scripts/dev/saas_staging.sh smoke

saas-status:
	@scripts/dev/saas_staging.sh status

saas-urls:
	@scripts/dev/saas_staging.sh urls

SERVICE ?= backend
saas-logs:
	@scripts/dev/saas_staging.sh logs $(SERVICE)

saas-down:
	@scripts/dev/saas_staging.sh down

saas-reset:
	@scripts/dev/saas_staging.sh reset

saas-nuke:
	@scripts/dev/saas_staging.sh nuke

# --- Cloudflare tunnels (Phase B) -------------------------------------------

saas-tunnel-up:
	@scripts/dev/saas_tunnel.sh up

saas-tunnel-test:
	@scripts/dev/saas_tunnel.sh smoke

saas-tunnel-down:
	@scripts/dev/saas_tunnel.sh down
