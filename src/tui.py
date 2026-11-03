import asyncio
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Header, Footer, Input, Button, Label, ProgressBar, Log, Static, Select

from src.core.text_splitter import TextSplitter
from src.api.mistral_client import MistralTTSClient
from src.api.factory import get_tts_client
from src.core.audio_compiler import AudioCompiler
from src.core.pipeline import prepare_text, run_pipeline, VoiceInput
from src.core.storage_retention import check_storage_budget
from src.core.config import get_translation_model, save_translation_model

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
    TRANSLATION_MODELS = [
        ("Ministral 8B - Default", "ministral-8b-latest"),
        ("Ministral 3B", "ministral-3b-latest"),
        ("Mistral Small", "mistral-small-latest"),
        ("Mistral Medium", "mistral-medium-latest"),
        ("Mistral Large", "mistral-large-latest"),
    ]

    def compose(self) -> ComposeResult:
        load_dotenv()
        api_key = os.getenv("MISTRAL_API_KEY", "")
        openai_key = os.getenv("OPENAI_API_KEY", "")
        current_trans_model = get_translation_model()
        valid_model_values = [v for _, v in self.TRANSLATION_MODELS]
        if current_trans_model not in valid_model_values:
            current_trans_model = "ministral-8b-latest"
        
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
                    yield Label("Trans Model:", classes="form-label")
                    yield Select(self.TRANSLATION_MODELS, value=current_trans_model, id="translation-model-select")
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
        elif event.select.id == "translation-model-select":
            model_name = event.value
            if model_name and model_name is not Select.BLANK:
                try:
                    save_translation_model(str(model_name))
                    self.log_message(f"Translation model updated: {model_name} (saved to .env)")
                except Exception as e:
                    self.log_message(f"Error saving translation model: {e}")

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
        trans_model_select = self.query_one("#translation-model-select", Select).value
        translation_model = str(trans_model_select) if (trans_model_select and trans_model_select is not Select.BLANK) else get_translation_model()

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
            openai_key=resolved_openai_key,
            translation_model=translation_model
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
        openai_key: str = "",
        translation_model: Optional[str] = None
    ):
        client = None
        try:
            engine = engine.strip().lower()
            tp = Path(text_path)
            op = Path(output_path)
            
            if not tp.exists():
                raise FileNotFoundError(f"Text file not found: {tp}")
            
            op.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(check_storage_budget)
            tts_api_key = openai_key if engine == "openai" else api_key
            client = get_tts_client(engine, tts_api_key)
            compiler = AudioCompiler()
            effective_translation_model = (translation_model or get_translation_model()) if target_lang else None
            voice = VoiceInput(voice_id, Path(voice_path) if voice_path else None)
            pb = self.query_one("#progress-bar", ProgressBar)

            async def translate(path, source, target, model):
                if not api_key:
                    raise ValueError("Mistral API key is required for translation.")
                translation_client = MistralTTSClient(api_key=api_key, translation_model=model)
                translated = await translation_client.translate_file(path, source, target)
                self.log_message(f"Translation completed. Saved to {translated}")
                return translated

            def report(event):
                if event.stage == 'Reading Text':
                    self.log_message("Reading input text...")
                elif event.stage == 'Translating':
                    self.query_one("#status-label", Static).update(f"Status: Translating to {target_lang}...")
                    self.log_message(f"Translating {tp.name} from {source_lang or 'English'} to {target_lang}...")
                elif event.stage == 'Splitting Text':
                    self.log_message("Splitting text into chunks...")
                elif event.stage == 'Text Ready':
                    pb.total = event.total
                    pb.progress = 0
                    self.log_message(f"Split into {event.total} chunks.")
                elif event.stage == 'Configuring Voice':
                    self.log_message(f"Cloning voice from {voice.reference}..." if voice.reference else
                                     f"Using voice: {voice.voice_id or ('alloy' if engine == 'openai' else 'en_paul_neutral')}")
                elif event.stage == 'Waiting for Cache':
                    self.query_one("#status-label", Static).update("Status: Waiting for cache...")
                elif event.stage == 'Generating Chunk':
                    self.query_one("#status-label", Static).update(f"Status: Generating chunk {event.current}/{event.total}...")
                elif event.stage == 'Chunk Ready':
                    pb.advance(1)
                    self.log_message(f"{'Reused' if event.cached else 'Generated'} chunk {event.current}/{event.total}")
                elif event.stage == 'Compiling Audiobook':
                    self.query_one("#status-label", Static).update("Status: Compiling audiobook...")
                    self.log_message("Compiling final audiobook...")

            prepared = await prepare_text(
                tp, splitter=TextSplitter(), source_lang=source_lang or None, target_lang=target_lang or None,
                translation_model=effective_translation_model, translate=translate, progress=report)
            await run_pipeline(prepared, client=client, engine=engine, voice=voice, output_path=op,
                               compiler_factory=lambda: compiler, progress=report)
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
            
            if client is not None and "voice" in str(e).lower() and "not found" in str(e).lower():
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
