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
   You should see `{"status":"ok","database":"ok","redis":"ok"}`.

## Run the tests

```
docker compose exec api pytest
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
