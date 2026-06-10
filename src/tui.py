from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Input, Button, Label, ProgressBar, Log, Static, Select

from src.core.text_splitter import TextSplitter
from src.api.mistral_client import MistralTTSClient
from src.core.audio_compiler import AudioCompiler

class BooksmithTUI(App):
    CSS = """
    Container {
        padding: 1;
    }
    .form-group {
        margin-bottom: 1;
        height: auto;
    }
    .form-row {
        height: 3;
        margin-bottom: 0;
        align: left middle;
    }
    .form-label {
        width: 15;
        content-align: right middle;
        margin-right: 1;
    }
    Input, Select {
        width: 1fr;
    }
    #start-btn {
        margin-top: 1;
        width: 100%;
        background: green;
    }
    #progress-container {
        margin-top: 1;
        border: solid gray;
        padding: 1;
        height: auto;
    }
    Log {
        margin-top: 1;
        height: 8;
        border: solid gray;
    }
    """

    TITLE = "Mistral-TTS-Booksmith"
    DEFAULT_VOICES = [
        ("Paul (Male)", "paul"),
        ("English Male (US)", "mistral-en-001"),
        ("English Female (US)", "mistral-en-002"),
        ("English Male (UK)", "mistral-en-003"),
        ("English Female (UK)", "mistral-en-004"),
    ]

    def compose(self) -> ComposeResult:
        yield Header()
        with Container():
            with Vertical(classes="form-group"):
                with Horizontal(classes="form-row"):
                    yield Label("Text Path:", classes="form-label")
                    yield Input(placeholder="path/to/text.txt", id="text-path")
                with Horizontal(classes="form-row"):
                    yield Label("Default Voice:", classes="form-label")
                    yield Select(self.DEFAULT_VOICES, prompt="Select a default voice", id="voice-select")
                with Horizontal(classes="form-row"):
                    yield Label("Manual Voice ID:", classes="form-label")
                    yield Input(placeholder="e.g. paul, mistral-en-001", id="manual-voice-id")
                with Horizontal(classes="form-row"):
                    yield Label("OR Voice Path:", classes="form-label")
                    yield Input(placeholder="path/to/voice.mp3 (for cloning)", id="voice-path")
                with Horizontal(classes="form-row"):
                    yield Label("Output Path:", classes="form-label")
                    yield Input(value="storage/output/audiobook.mp3", id="output-path")
                with Horizontal(classes="form-row"):
                    yield Label("API Key:", classes="form-label")
                    yield Input(placeholder="Mistral AI API Key", password=True, id="api-key")
                
                yield Button("Start Generation", variant="success", id="start-btn")
            
            with Vertical(id="progress-container"):
                yield Label("Overall Progress:")
                yield ProgressBar(total=100, id="progress-bar")
                yield Static("Status: Ready", id="status-label")
            
            yield Log(id="log")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "start-btn":
            self.start_processing()

    def log_message(self, message: str):
        self.query_one("#log", Log).write_line(message)

    def start_processing(self):
        text_path = self.query_one("#text-path", Input).value.strip()
        voice_path = self.query_one("#voice-path", Input).value.strip()
        voice_id = self.query_one("#voice-select", Select).value
        manual_voice_id = self.query_one("#manual-voice-id", Input).value.strip()
        output_path = self.query_one("#output-path", Input).value.strip()
        api_key = self.query_one("#api-key", Input).value.strip()

        if not text_path or not output_path or not api_key:
            self.log_message("Error: Text Path, Output Path, and API Key are required.")
            return

        # Priority: Manual ID > Select List > Voice Path
        final_voice_id = manual_voice_id if manual_voice_id else (voice_id if voice_id is not Select.BLANK else None)

        if not voice_path and not final_voice_id:
            self.log_message("Error: A Voice ID (selected or manual) or a Voice Path must be provided.")
            return

        self.query_one("#start-btn", Button).disabled = True
        self.query_one("#status-label", Static).update("Status: Initializing...")
        self.run_worker(self.process_book(text_path, voice_path, final_voice_id, output_path, api_key))

    async def process_book(self, text_path: str, voice_path: str, voice_id: str, output_path: str, api_key: str):
        try:
            tp = Path(text_path)
            op = Path(output_path)
            
            if not tp.exists():
                raise FileNotFoundError(f"Text file not found: {tp}")
            
            op.parent.mkdir(parents=True, exist_ok=True)
            cache_dir = Path("storage/cache")
            cache_dir.mkdir(parents=True, exist_ok=True)

            splitter = TextSplitter()
            client = MistralTTSClient(api_key=api_key)
            compiler = AudioCompiler()

            self.log_message("Reading text and splitting into chunks...")
            with open(tp, "r") as f:
                text = f.read()
            chunks = splitter.split(text)
            self.log_message(f"Split into {len(chunks)} chunks.")

            if voice_path:
                vp = Path(voice_path)
                if not vp.exists():
                    raise FileNotFoundError(f"Voice file not found: {vp}")
                self.log_message(f"Cloning voice from {vp}...")
                await client.clone_voice(vp)
            else:
                self.log_message(f"Using default voice: {voice_id}")
                client.set_voice_id(voice_id)
            
            pb = self.query_one("#progress-bar", ProgressBar)
            pb.total = len(chunks)
            pb.progress = 0
            
            chunk_files = []
            for i, chunk in enumerate(chunks):
                self.query_one("#status-label", Static).update(f"Status: Generating chunk {i+1}/{len(chunks)}...")
                chunk_path = cache_dir / f"chunk_{i:04d}.mp3"
                await client.generate_audio(chunk, chunk_path)
                chunk_files.append(chunk_path)
                pb.advance(1)
                self.log_message(f"Generated chunk {i+1}/{len(chunks)}")

            self.query_one("#status-label", Static).update("Status: Compiling audiobook...")
            self.log_message("Compiling final audiobook...")
            compiler.compile(chunk_files, op)
            
            self.query_one("#status-label", Static).update("Status: Completed!")
            self.log_message(f"Success! Audiobook saved to {op}")
            
        except Exception as e:
            self.log_message(f"Error: {str(e)}")
            if "invalid model" in str(e).lower():
                self.log_message("Attempting to fetch available models...")
                models = await client.list_models()
                if models:
                    self.log_message(f"Available models: {', '.join(models)}")
                else:
                    self.log_message("Could not fetch available models.")
            
            if "voice" in str(e).lower() and "not found" in str(e).lower():
                self.log_message("Attempting to fetch available voices...")
                voices = await client.list_voices()
                if voices:
                    voice_str = ", ".join([f"{v['name']} ({v['id']})" for v in voices])
                    self.log_message(f"Available voices: {voice_str}")
                else:
                    self.log_message("Could not fetch available voices.")
            self.query_one("#status-label", Static).update("Status: Error")
        finally:
            self.query_one("#start-btn", Button).disabled = False

if __name__ == "__main__":
    app = BooksmithTUI()
    app.run()
