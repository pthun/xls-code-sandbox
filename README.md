# Double App Scaffold

This workspace contains a minimal full-stack setup with a React Router 7 frontend and a FastAPI backend. The frontend collects a number from the user, sends it to the backend, and displays the doubled result.

## Frontend (React Router 7 + Vite)

1. `cd frontend`
2. Install dependencies (already done by the scaffold, run again if needed): `npm install`
3. Start the dev server (configured for `http://localhost:3100`): `npm run dev`

The main UI lives in `frontend/app/routes/_index.tsx` and uses a simple client-side fetch to call the backend.

## Backend (FastAPI)

1. `cd backend`
2. Create a virtual environment and activate it (example shown for macOS/Linux):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
3. Install the dependencies: `pip install -r requirements.txt`
4. Start the API (runs on `http://localhost:3101`):
   ```bash
   uvicorn app.main:app --reload --port 3101
   ```

### Endpoints

- `GET /` – Health check returning a typed status payload.
- `POST /api/double` – Accepts `{ "value": <number> }` and responds with `{ "input": <number>, "doubled": <number>, "message": <string> }`.

### Example request

```bash
curl -X POST \
  http://localhost:3101/api/double \
  -H "Content-Type: application/json" \
  -d '{"value": 21}'
```

This returns:

```json
{
  "input": 21.0,
  "doubled": 42.0,
  "message": "21.0 doubled is 42.0"
}
```

## Development Notes

- CORS is configured to allow the frontend dev server at `http://localhost:3100`.
- Adjust ports if 3100/3101 are taken by updating `frontend/vite.config.ts` and the `uvicorn` command respectively.
