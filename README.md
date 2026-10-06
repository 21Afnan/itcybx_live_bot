# IT Cybx Website Chatbot

AI sales assistant for itcybx.co.uk (English and Arabic). It answers visitor
questions, collects leads and points visitors to book a Growth Audit.

## Run it locally

You need Docker Desktop running and a Supabase project (the database).

1. Create your settings file (first time only):
   ```
   copy .env.example .env
   ```
   Then open `.env` and fill in the real values, including `DATABASE_URL`
   from Supabase (Connect → Session pooler).
2. Start everything:
   ```
   docker compose up -d --build
   ```
3. Check it is working:
   ```
   curl http://localhost:8000/health
   ```
   You should see `{"status":"ok","db":"ok","redis":"ok"}`.
4. The database tables are created and updated automatically each time the
   API container starts (`alembic upgrade head`). If the logs show
   `WARNING: database migrations failed`, fix the database connection and
   run it by hand:
   ```
   docker compose exec api alembic upgrade head
   ```

## Production checklist

In the server's `.env`:

- `APP_ENV=production` — also re-checks the website once at start-up, so a
  redeploy never brings back older knowledge files.
- `FORWARDED_ALLOW_IPS` — the IP(s) of the proxy in front of the API
  (Nginx, load balancer). Without it every visitor looks like the proxy and
  they all share one rate limit.
- `ALLOWED_ORIGINS` — remove `http://localhost:8080`.

Migrations run on container start-up; check the logs for
`WARNING: database migrations failed` after each deploy. To keep the
rollback history of the weekly sync across redeploys, mount a volume at
`/code/knowledge/.history` (the newest 20 backups are kept). With more than
one API container, each one keeps its own knowledge files up to date; only
one emails the team about the changes. Allow at least 30 seconds for the
container to stop (`stop_grace_period`), so replies and lead alerts that
are still running can finish.

Lead alerts (email and Google Sheet row) go out right after a lead
completes. If a channel fails, an hourly job retries only that channel for
up to 7 days, so an SMTP or Google outage doesn't lose leads.

## Run the tests

```
docker compose exec api pytest
```

Without Docker, use Python 3.11 or newer: on older versions the chat and
conversation-flow tests are skipped (LangGraph streaming needs 3.11+). With
[uv](https://docs.astral.sh/uv/), from `backend/`:

```
uv venv --python 3.12 .venv
uv pip install --python .venv -r requirements.txt
.venv\Scripts\python -m pytest
```

## Stop everything

```
docker compose down
```

## Folders

- `backend/` — everything that runs on the server: the API, bot logic, AI,
  knowledge, leads, database, and tests
- `widget/` — the chat bubble shown on the website (added in Step 9)
- `docker-compose.yml` — starts the backend and Redis together (the database
  is on Supabase)
