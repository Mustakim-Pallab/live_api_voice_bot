# Gemini Live API Real-Time Voice Bot

This project is a real-time interactive voice bot using Gemini Live API with model `gemini-3.1-flash-live-preview`.

- Browser captures microphone audio.
- Backend streams PCM audio chunks to Gemini Live.
- Gemini returns streaming voice + text.
- Browser plays audio chunks in near real time.

## Project structure

- `main.py` - app entrypoint
- `app/server.py` - FastAPI app, websocket endpoint
- `app/gemini_live.py` - Gemini Live bridge logic
- `web/index.html` - UI
- `web/app.js` - mic capture + streaming + playback
- `Dockerfile`, `docker-compose.yml` - container runtime

## Prerequisites

- A Gemini API key from Google AI Studio.
- Docker and Docker Compose.
- Chrome/Edge/Firefox with microphone permission.

## Quick start (Docker)

1. Create `.env` from the example and set your API key.

```bash
cp .env.example .env
```

2. Edit `.env` and set `GEMINI_API_KEY`.

3. Build and run.

```bash
docker compose up --build
```

4. Open the app.

```bash
xdg-open http://localhost:8000
```

5. Click **Connect** -> **Start Talking**.

## Run locally (without Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 main.py
```

Then open `http://localhost:8000`.

## Notes

- Mic access usually requires `localhost` or HTTPS.
- The backend keeps your API key server-side (not exposed to browser JS).
- Default voice is `Aoede` and can be changed with `VOICE_NAME`.
- Input audio rate is 16k PCM; output defaults to 24k PCM.

## Health check

```bash
curl -s http://localhost:8000/health
```

# live_api_voice_bot
