# DJ Replacement

A small Python desktop app that takes typed or spoken requests and queues matching songs in the active Spotify account instead of interrupting the current track.

## What it does

- Accepts text prompts like `queue Daft Punk One More Time` or `play something by Fleetwood Mac`.
- Accepts microphone input when speech dependencies are installed.
- Searches Spotify and adds the best match to the queue.
- Uses OpenAI for friendlier command parsing when `OPENAI_API_KEY` is set.
- Falls back to a local parser when no OpenAI key is configured.
- Can be packaged into a Windows `.exe` with PyInstaller.

## Spotify setup

1. Create an app at <https://developer.spotify.com/dashboard>.
2. Add this redirect URI to the Spotify app settings:

   ```text
   http://localhost:8888/callback
   ```

3. Copy `.env.example` to `.env`.
4. Fill in `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, and `SPOTIPY_REDIRECT_URI`.

Spotify queue control requires an active Spotify session on the account and may require Spotify Premium.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

On macOS or Linux, activate the environment with:

```bash
source .venv/bin/activate
```

## Build the exe

From Windows:

```bash
pyinstaller --noconfirm --onefile --windowed --name DJReplacement app.py
```

The executable will be created in:

```text
dist\DJReplacement.exe
```

Keep your `.env` file next to the executable, or set the same values as environment variables before launching it.

## Notes about microphone support

Speech input uses the `SpeechRecognition` package. `PyAudio` can sometimes need platform-specific install steps. If installing `PyAudio` fails on Windows, try:

```bash
pip install pipwin
pipwin install pyaudio
```
