# Deploying damka.uz (V2)

The whole stack is env-driven, so **DevOps mostly fills `.env` + sets up one host
nginx, then runs docker compose (backend) and PM2/build (frontend)**. No per-server
code changes.

```
                 ┌────────────── HOST nginx (TLS + certbot) ──────────────┐
 damka.uz ──────▶│  :443 → 127.0.0.1:3000  (Nuxt SPA, PM2 or static)      │
 cp.damka.uz ───▶│  :443 → 127.0.0.1:8080  (docker compose nginx: WS+API) │
                 └────────────────────────────────────────────────────────┘
        backend docker compose: nginx → web (uvicorn ×N) ── postgres ── redis ── celery
```

TLS is terminated by the host nginx (`docs/deploy/nginx.conf`); it forwards
`X-Forwarded-Proto`, which `config/settings/production.py` trusts.

---

## Backend — `damka-back-v2`

1. Clone to the server, e.g. `/opt/damka/damka-back-v2`.
2. `cp .env.production.example .env` and fill it in. Key ones:
   - `DJANGO_SETTINGS_MODULE=config.settings.production`, `DJANGO_DEBUG=False`
   - a strong `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS=cp.damka.uz`,
     `DJANGO_CSRF_TRUSTED_ORIGINS`, `CORS_ALLOWED_ORIGINS=https://damka.uz`
   - DB/Redis URLs, `SMS_TEST_MODE=True` (until Eskiz is live), Eskiz/SMTP creds
   - `WEB_CONCURRENCY` — **leave unset**; `/start` auto-scales to the box's CPUs.
3. Point compose at the prod env + don't expose the compose nginx publicly:
   - in `docker-compose.yml`, set `web`/`celery_worker` `env_file: .env`
     (currently `.env.docker`) and the `nginx` service `ports: "127.0.0.1:8080:80"`.
4. `docker compose build && docker compose up -d`
   - `/start` runs `collectstatic` + `migrate`, then uvicorn with N workers.
5. Redeploys: `git pull && docker compose build web celery_worker && docker compose up -d`
   (the `.github/workflows/deploy.yml` does this over SSH on push to `master`).

**Admin:** phone `+998900000001` / user `testadmin`, password from
`TEST_ADMIN_PASSWORD`. Change or delete it in prod.

**SMS/email:** with `SMS_TEST_MODE=True` the code is always `0000` and nothing is
sent — test the flow, then set it `False` once Eskiz + SMTP are configured.

---

## Frontend — `damka-front-v2` (Nuxt 4, `ssr: false` → SPA)

Because it's a SPA, `BASE_URL`/`BASE_WS_URL` are **baked at build time**.

1. Clone to e.g. `/srv/damka/damka-front-v2`; `nvm use` (Node 22, see `.nvmrc`).
2. `cp .env.production.example .env` → `BASE_URL=https://cp.damka.uz`,
   `BASE_WS_URL=wss://cp.damka.uz`.
3. `npm ci && npm run build` (reads the env, outputs `.output/`).
4. Serve it — two options:
   - **Static (simplest):** nginx serves `.output/public`
     (`root .../.output/public; try_files $uri $uri/ /index.html;`). No Node process.
   - **PM2 (node server / parity):** `pm2 start ecosystem.config.cjs && pm2 save`
     → runs `.output/server/index.mjs` on `127.0.0.1:3000`.
5. Redeploys: `git pull && npm ci && npm run build && pm2 reload ecosystem.config.cjs`
   (or just re-run the static build).

---

## Host nginx + TLS (one-time)

1. Copy `docs/deploy/nginx.conf` → `/etc/nginx/sites-available/damka.conf`, adjust
   domains/paths, symlink into `sites-enabled/`.
2. Issue certs:
   `certbot certonly --webroot -w /var/www/certbot -d damka.uz -d www.damka.uz -d cp.damka.uz`
3. `nginx -t && systemctl reload nginx`. Certbot auto-renews via its timer.

---

## DevOps checklist (the short version)

- [ ] DNS: `damka.uz`, `cp.damka.uz` → server IP
- [ ] Backend: fill `.env`, `docker compose up -d`
- [ ] Frontend: fill `.env`, `npm ci && npm run build`, serve (nginx static or PM2)
- [ ] Host nginx: install `nginx.conf`, run certbot, reload
- [ ] Flip `SMS_TEST_MODE=False` once Eskiz/SMTP are configured
