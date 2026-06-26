import os
from pathlib import Path
from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Input, Button, Label, ProgressBar, Log, Static, Select

from src.core.text_splitter import TextSplitter
from src.api.mistral_client import MistralTTSClient
from src.api.factory import get_tts_client
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
        ("Paul (Male - Neutral)", "en_paul_neutral"),
        ("Sarah (Female - Expressive)", "en_sarah_expressive"),
    ]
    OPENAI_VOICES = [
        ("Alloy (Neutral)", "alloy"),
        ("Echo (Balanced)", "echo"),
        ("Fable (Narrative)", "fable"),
        ("Onyx (Deep/Male)", "onyx"),
        ("Nova (Energetic/Female)", "nova"),
        ("Shimmer (Professional)", "shimmer"),
    ]

    def compose(self) -> ComposeResult:
        load_dotenv()
        api_key = os.getenv("MISTRAL_API_KEY", "")
        openai_key = os.getenv("OPENAI_API_KEY", "")
        
        yield Header()
        with Container():
            with Vertical(classes="form-group"):
                with Horizontal(classes="form-row"):
                    yield Label("Text Path:", classes="form-label")
                    yield Input(placeholder="path/to/text.txt", id="text-path")
                with Horizontal(classes="form-row"):
                    yield Label("Source Lang:", classes="form-label")
                    yield Input(placeholder="e.g. English (optional)", id="source-lang")
                with Horizontal(classes="form-row"):
                    yield Label("Target Lang:", classes="form-label")
                    yield Input(placeholder="e.g. Spanish (optional)", id="target-lang")
                with Horizontal(classes="form-row"):
                    yield Label("TTS Engine:", classes="form-label")
                    yield Select([("Mistral", "mistral"), ("OpenAI", "openai")], value="mistral", id="engine-select")
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
                    yield Input(value=api_key, placeholder="Mistral AI API Key", password=True, id="api-key")
                with Horizontal(classes="form-row"):
                    yield Label("OpenAI Key:", classes="form-label")
                    yield Input(value=openai_key, placeholder="OpenAI API Key (optional if in .env)", password=True, id="openai-key")
                
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

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "engine-select":
            engine = event.value
            voice_select = self.query_one("#voice-select", Select)
            voice_path_input = self.query_one("#voice-path", Input)
            manual_voice_id_input = self.query_one("#manual-voice-id", Input)
            
            if engine == "openai":
                voice_select.set_options(self.OPENAI_VOICES)
                voice_select.value = "alloy"
                voice_path_input.value = ""
                voice_path_input.disabled = True
                manual_voice_id_input.value = ""
                manual_voice_id_input.disabled = True
            else:
                voice_select.set_options(self.DEFAULT_VOICES)
                voice_select.value = "en_paul_neutral"
                voice_path_input.disabled = False
                manual_voice_id_input.disabled = False

    def log_message(self, message: str):
        self.query_one("#log", Log).write_line(message)

    def start_processing(self):
        text_path = self.query_one("#text-path", Input).value.strip()
        voice_path = self.query_one("#voice-path", Input).value.strip()
        voice_id = self.query_one("#voice-select", Select).value
        manual_voice_id = self.query_one("#manual-voice-id", Input).value.strip()
        output_path = self.query_one("#output-path", Input).value.strip()
        api_key = self.query_one("#api-key", Input).value.strip()
        openai_key = self.query_one("#openai-key", Input).value.strip()
        engine = self.query_one("#engine-select", Select).value
        source_lang = self.query_one("#source-lang", Input).value.strip()
        target_lang = self.query_one("#target-lang", Input).value.strip()

        if not text_path or not output_path:
            self.log_message("Error: Text Path and Output Path are required.")
            return

        if engine == "mistral" and not api_key:
            self.log_message("Error: Mistral API Key is required for the Mistral engine.")
            return

        resolved_openai_key = openai_key or os.getenv("OPENAI_API_KEY", "")
        if engine == "openai":
            if voice_path:
                self.log_message("Error: OpenAI TTS does not support voice cloning. Please select an OpenAI preset voice instead.")
                return
            if not resolved_openai_key:
                self.log_message("Error: OpenAI API Key is required for the OpenAI engine.")
                return

        if target_lang and not api_key:
            self.log_message("Error: Mistral API Key is required for translation.")
            return

        # Priority: Manual ID > Select List > Voice Path
        final_voice_id = manual_voice_id if manual_voice_id else (voice_id if voice_id is not Select.BLANK else None)

        if not voice_path and not final_voice_id:
            self.log_message("Error: A Voice ID (selected or manual) or a Voice Path must be provided.")
            return

        self.query_one("#start-btn", Button).disabled = True
        self.query_one("#status-label", Static).update("Status: Initializing...")
        self.run_worker(self.process_book(
            text_path=text_path,
            voice_path=voice_path,
            voice_id=final_voice_id,
            output_path=output_path,
            api_key=api_key,
            source_lang=source_lang,
            target_lang=target_lang,
            engine=engine,
            openai_key=resolved_openai_key
        ))

    async def process_book(
        self,
        text_path: str,
        voice_path: str,
        voice_id: str,
        output_path: str,
        api_key: str,
        source_lang: str = "",
        target_lang: str = "",
        engine: str = "mistral",
        openai_key: str = ""
    ):
        try:
            tp = Path(text_path)
            op = Path(output_path)
            
            if not tp.exists():
                raise FileNotFoundError(f"Text file not found: {tp}")
            
            op.parent.mkdir(parents=True, exist_ok=True)
            cache_dir = Path("storage/cache")
            cache_dir.mkdir(parents=True, exist_ok=True)

            splitter = TextSplitter()
            
            # Resolve correct TTS API key
            tts_api_key = openai_key if engine == "openai" else api_key
            # Instantiate client via factory
            client = get_tts_client(engine, tts_api_key)
            
            compiler = AudioCompiler()

            if target_lang:
                if not api_key:
                    raise ValueError("Mistral API key is required for translation.")
                source = source_lang if source_lang else "English"
                self.query_one("#status-label", Static).update(f"Status: Translating to {target_lang}...")
                self.log_message(f"Translating {tp.name} from {source} to {target_lang}...")
                translation_client = MistralTTSClient(api_key=api_key)
                tp = await translation_client.translate_file(tp, source, target_lang)
                self.log_message(f"Translation completed. Saved to {tp}")

            self.log_message("Reading text and splitting into chunks...")
            from src.core.epub_parser import read_input_text
            text = read_input_text(tp)
            chunks = splitter.split(text)
            self.log_message(f"Split into {len(chunks)} chunks.")

            if engine == "openai":
                self.log_message(f"Using OpenAI voice: {voice_id}")
                client.set_voice_id(voice_id)
            else:  # engine == "mistral"
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
            if "invalid model" in str(e).lower() and hasattr(client, "list_models"):
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
                    voice_str = ", ".join([f"ID: {v['id']} (Name: {v['name']})" for v in voices])
                    self.log_message(f"Available voices: {voice_str}")
                else:
                    self.log_message("Could not fetch available voices.")
            self.query_one("#status-label", Static).update("Status: Error")
        finally:
            self.query_one("#start-btn", Button).disabled = False

if __name__ == "__main__":
    app = BooksmithTUI()
    app.run()
