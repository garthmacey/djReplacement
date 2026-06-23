import json
import os
import queue
import re
import threading
import tkinter as tk
from dataclasses import dataclass
from tkinter import messagebox, ttk

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

try:
    import speech_recognition as sr
except ImportError:  # Speech input remains optional.
    sr = None

try:
    from openai import OpenAI
except ImportError:  # AI parsing remains optional.
    OpenAI = None


SPOTIFY_SCOPES = "user-modify-playback-state user-read-playback-state"


@dataclass
class MusicCommand:
    action: str
    query: str


class CommandParser:
    def __init__(self):
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        self.client = OpenAI(api_key=self.openai_api_key) if OpenAI and self.openai_api_key else None

    def parse(self, user_text: str) -> MusicCommand:
        cleaned = user_text.strip()
        if not cleaned:
            raise ValueError("Enter a song, artist, album, or playlist request.")

        if self.client:
            try:
                return self._parse_with_openai(cleaned)
            except Exception:
                pass

        return self._parse_locally(cleaned)

    def _parse_with_openai(self, user_text: str) -> MusicCommand:
        response = self.client.chat.completions.create(
            model=self.openai_model,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract a Spotify music queue command. Return only JSON with "
                        "keys action and query. action must be queue_track, queue_album, "
                        "queue_artist, or queue_playlist. query is the Spotify search query."
                    ),
                },
                {"role": "user", "content": user_text},
            ],
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content)
        action = payload.get("action", "queue_track")
        query = payload.get("query", user_text).strip()
        return MusicCommand(action=action, query=query)

    def _parse_locally(self, user_text: str) -> MusicCommand:
        text = user_text.strip()
        lowered = text.lower()

        replacements = [
            r"^(please\s+)?(queue|add|put on|play)\s+",
            r"\s+(to|in)\s+(the\s+)?queue$",
            r"^can you\s+",
        ]
        for pattern in replacements:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()

        if "playlist" in lowered:
            return MusicCommand(action="queue_playlist", query=self._remove_word(text, "playlist"))
        if "album" in lowered:
            return MusicCommand(action="queue_album", query=self._remove_word(text, "album"))
        if re.search(r"\bby\s+[\w\s]+$", lowered) and not re.search(r"\bsong\b|\btrack\b", lowered):
            return MusicCommand(action="queue_track", query=text)
        if lowered.startswith("artist "):
            return MusicCommand(action="queue_artist", query=text[7:].strip())
        return MusicCommand(action="queue_track", query=text)

    @staticmethod
    def _remove_word(value: str, word: str) -> str:
        return re.sub(rf"\b{re.escape(word)}\b", "", value, flags=re.IGNORECASE).strip()


class SpotifyQueueClient:
    def __init__(self):
        self.spotify = spotipy.Spotify(
            auth_manager=SpotifyOAuth(
                scope=SPOTIFY_SCOPES,
                open_browser=True,
                cache_path=".spotify_token_cache",
            )
        )

    def queue(self, command: MusicCommand) -> list[str]:
        if command.action == "queue_playlist":
            return self._queue_collection(command.query, "playlist")
        if command.action == "queue_album":
            return self._queue_collection(command.query, "album")
        if command.action == "queue_artist":
            return self._queue_artist_top_tracks(command.query)
        return [self._queue_track(command.query)]

    def _queue_track(self, query: str) -> str:
        track = self._first_result(query, "track")
        self.spotify.add_to_queue(track["uri"])
        artists = ", ".join(artist["name"] for artist in track["artists"])
        return f'{track["name"]} - {artists}'

    def _queue_collection(self, query: str, collection_type: str) -> list[str]:
        collection = self._first_result(query, collection_type)
        if collection_type == "album":
            tracks = self.spotify.album_tracks(collection["id"], limit=20)["items"]
        else:
            playlist_items = self.spotify.playlist_items(collection["id"], limit=20, additional_types=("track",))
            tracks = [item["track"] for item in playlist_items["items"] if item.get("track")]

        queued = []
        for track in tracks[:10]:
            self.spotify.add_to_queue(track["uri"])
            queued.append(track["name"])
        return queued

    def _queue_artist_top_tracks(self, query: str) -> list[str]:
        artist = self._first_result(query, "artist")
        tracks = self.spotify.artist_top_tracks(artist["id"])["tracks"][:10]
        queued = []
        for track in tracks:
            self.spotify.add_to_queue(track["uri"])
            queued.append(track["name"])
        return queued

    def _first_result(self, query: str, search_type: str) -> dict:
        results = self.spotify.search(q=query, type=search_type, limit=1)
        container = results[f"{search_type}s"]["items"]
        if not container:
            raise ValueError(f'No Spotify {search_type} found for "{query}".')
        return container[0]


class DJReplacementApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("DJ Replacement")
        self.geometry("760x560")
        self.minsize(620, 460)

        self.parser = CommandParser()
        self.spotify_client = None
        self.events = queue.Queue()
        self.busy = False

        self._configure_style()
        self._build_ui()
        self.after(100, self._drain_events)

    def _configure_style(self):
        self.configure(bg="#f7f7f5")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background="#f7f7f5")
        style.configure("TLabel", background="#f7f7f5", foreground="#1f2328", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("TButton", font=("Segoe UI", 10), padding=(12, 8))
        style.configure("Accent.TButton", background="#1db954", foreground="#0b1b10")
        style.map("Accent.TButton", background=[("active", "#21cf60")])

    def _build_ui(self):
        root = ttk.Frame(self, padding=24)
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root)
        header.pack(fill=tk.X)
        ttk.Label(header, text="DJ Replacement", style="Title.TLabel").pack(side=tk.LEFT)
        self.auth_status = ttk.Label(header, text="Spotify: not connected")
        self.auth_status.pack(side=tk.RIGHT)

        prompt_frame = ttk.Frame(root)
        prompt_frame.pack(fill=tk.X, pady=(28, 12))
        ttk.Label(prompt_frame, text="Request").pack(anchor=tk.W)
        self.prompt = tk.Text(prompt_frame, height=4, wrap=tk.WORD, font=("Segoe UI", 12), padx=12, pady=10)
        self.prompt.pack(fill=tk.X, pady=(6, 0))
        self.prompt.bind("<Control-Return>", lambda _event: self.queue_request())

        controls = ttk.Frame(root)
        controls.pack(fill=tk.X, pady=(8, 20))
        self.queue_button = ttk.Button(controls, text="Queue", style="Accent.TButton", command=self.queue_request)
        self.queue_button.pack(side=tk.LEFT)
        self.listen_button = ttk.Button(controls, text="Listen", command=self.listen_for_request)
        self.listen_button.pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(controls, text="Clear", command=self.clear_prompt).pack(side=tk.LEFT, padx=(10, 0))

        self.status = ttk.Label(root, text="Type a request, then queue it to Spotify.")
        self.status.pack(anchor=tk.W, pady=(0, 8))

        ttk.Label(root, text="Queued").pack(anchor=tk.W)
        list_frame = ttk.Frame(root)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 0))
        self.queued_list = tk.Listbox(
            list_frame,
            font=("Segoe UI", 11),
            activestyle="none",
            bg="#ffffff",
            fg="#1f2328",
            selectbackground="#d7f8e2",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground="#dadde1",
        )
        self.queued_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.queued_list.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.queued_list.configure(yscrollcommand=scrollbar.set)

    def queue_request(self):
        user_text = self.prompt.get("1.0", tk.END).strip()
        if not user_text:
            self._set_status("Enter a request first.")
            return
        self._run_background(self._queue_worker, user_text)

    def listen_for_request(self):
        if sr is None:
            messagebox.showerror("Speech unavailable", "Install SpeechRecognition and PyAudio to use speech input.")
            return
        self._run_background(self._listen_worker)

    def clear_prompt(self):
        self.prompt.delete("1.0", tk.END)

    def _queue_worker(self, user_text: str):
        self.events.put(("status", "Understanding request..."))
        command = self.parser.parse(user_text)
        self.events.put(("status", "Connecting to Spotify..."))
        if self.spotify_client is None:
            self.spotify_client = SpotifyQueueClient()
            self.events.put(("auth", "Spotify: connected"))
        self.events.put(("status", f'Queueing "{command.query}"...'))
        queued = self.spotify_client.queue(command)
        self.events.put(("queued", queued))
        self.events.put(("status", f"Queued {len(queued)} item(s)."))

    def _listen_worker(self):
        recognizer = sr.Recognizer()
        self.events.put(("status", "Listening..."))
        with sr.Microphone() as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio = recognizer.listen(source, timeout=8, phrase_time_limit=10)
        self.events.put(("status", "Transcribing..."))
        text = recognizer.recognize_google(audio)
        self.events.put(("prompt", text))
        self.events.put(("status", "Speech captured. Review it, then queue."))

    def _run_background(self, target, *args):
        if self.busy:
            self._set_status("Still working on the previous request.")
            return
        self.busy = True
        self._set_controls_enabled(False)

        def runner():
            try:
                target(*args)
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("done", None))

        threading.Thread(target=runner, daemon=True).start()

    def _drain_events(self):
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "status":
                self._set_status(payload)
            elif event == "auth":
                self.auth_status.configure(text=payload)
            elif event == "prompt":
                self.prompt.delete("1.0", tk.END)
                self.prompt.insert("1.0", payload)
            elif event == "queued":
                for item in payload:
                    self.queued_list.insert(tk.END, item)
            elif event == "error":
                self._set_status("Something went wrong.")
                messagebox.showerror("DJ Replacement", payload)
            elif event == "done":
                self.busy = False
                self._set_controls_enabled(True)

        self.after(100, self._drain_events)

    def _set_status(self, value: str):
        self.status.configure(text=value)

    def _set_controls_enabled(self, enabled: bool):
        state = tk.NORMAL if enabled else tk.DISABLED
        self.queue_button.configure(state=state)
        self.listen_button.configure(state=state)


def main():
    load_dotenv()
    missing = [name for name in ("SPOTIPY_CLIENT_ID", "SPOTIPY_CLIENT_SECRET", "SPOTIPY_REDIRECT_URI") if not os.getenv(name)]
    if missing:
        messagebox.showwarning(
            "Spotify credentials missing",
            "Create a .env file first. Missing: " + ", ".join(missing),
        )
    app = DJReplacementApp()
    app.mainloop()


if __name__ == "__main__":
    main()
