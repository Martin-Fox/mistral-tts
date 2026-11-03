import asyncio
import argparse
import logging
import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich.panel import Panel
from rich.logging import RichHandler
from src.core.text_splitter import TextSplitter
from src.core.config import get_translation_model
from src.api.mistral_client import MistralTTSClient
from src.api.factory import get_tts_client
from src.core.audio_compiler import AudioCompiler
from src.core.pipeline import prepare_text, run_pipeline, VoiceInput
from src.core.storage_retention import check_storage_budget

# Configure Rich logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler(rich_tracebacks=True)]
)
logger = logging.getLogger("booksmith")
console = Console()

class BooksmithCLI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.splitter = TextSplitter()
        self.compiler = AudioCompiler()
        self.base_cache_dir = Path("storage/cache")
        self.base_cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_dir = self.base_cache_dir
        self.manifest_path: Optional[Path] = None

    @property
    def cache_dir(self) -> Path:
        return self._cache_dir

    @cache_dir.setter
    def cache_dir(self, value: Path):
        self._cache_dir = value
        if value.parent != self.base_cache_dir:
            self.base_cache_dir = value

    async def run(
        self,
        text_path: Path,
        voice_path: Path,
        output_path: Path,
        source_lang: Optional[str] = None,
        target_lang: Optional[str] = None,
        engine: str = "mistral",
        openai_key: Optional[str] = None
    ):
        console.print(Panel.fit("Mistral-TTS-Booksmith", style="bold magenta"))
        await asyncio.to_thread(check_storage_budget)

        engine = engine.strip().lower()
        # Resolve the correct TTS API key and get client
        tts_api_key = openai_key if engine == "openai" else self.api_key
        if not tts_api_key:
            raise ValueError(f"API key is required for the selected engine ({engine}).")
        
        client = get_tts_client(engine, tts_api_key)

        effective_translation_model = get_translation_model() if target_lang else None

        async def translate(path, source, target, model):
            if not self.api_key:
                raise ValueError("Mistral API key is required for translation.")
            translation_client = MistralTTSClient(api_key=self.api_key, translation_model=model)
            translated = await translation_client.translate_file(path, source, target)
            logger.info(f"Translation completed. Translated file: {translated}")
            return translated

        with console.status("[bold green]Reading input text...") as status:
            def input_progress(event):
                if event.stage == 'Translating':
                    status.update(f"[bold blue]Translating text from {source_lang or 'English'} to {target_lang}...")
                elif event.stage == 'Splitting Text':
                    status.update("[bold green]Splitting text...")
                elif event.stage == 'Text Ready':
                    logger.info(f"Text split into {event.total} semantic chunks (total characters: {event.characters}).")
            prepared = await prepare_text(
                text_path, splitter=self.splitter, source_lang=source_lang, target_lang=target_lang,
                translation_model=effective_translation_model, translate=translate, progress=input_progress)

        voice_str = str(voice_path).strip() if voice_path else ""
        voice_provided = bool(voice_str and voice_str != ".")
        reference = voice_path if voice_provided and voice_path.exists() else None
        voice = VoiceInput(voice_id=voice_str if voice_provided else None, reference=reference)

        def cache_ready(directory):
            self.cache_dir = directory
            self.manifest_path = directory / "manifest.json"

        with Progress(
            SpinnerColumn(), TextColumn("[progress.description]{task.description}"), BarColumn(),
            TaskProgressColumn(), TimeRemainingColumn(), console=console
        ) as progress:
            task = progress.add_task("[cyan]Configuring voice...", total=None)
            def report(event):
                if event.stage == 'Waiting for Cache':
                    logger.info("Waiting for exclusive access to the audio cache...")
                    progress.update(task, description="[cyan]Waiting for cache...")
                elif event.stage == 'Generating Audio':
                    progress.update(task, total=event.total, description="[cyan]Generating audio chunks...")
                elif event.stage == 'Chunk Ready':
                    progress.advance(task)
                elif event.stage == 'Compiling Audiobook':
                    progress.update(task, description="[yellow]Compiling final audiobook...")
            result = await run_pipeline(
                prepared, client=client, engine=engine, voice=voice, output_path=output_path,
                compiler_factory=lambda: self.compiler, cache_root=self.base_cache_dir,
                progress=report, cache_ready=cache_ready)
        logger.info(
            f"Audiobook compilation verified: duration {result.compilation.get('output_duration', 0):.2f}s "
            f"(expected ~{result.compilation.get('expected_duration', 0):.2f}s across {result.chunk_count} chunks).")
        console.print(Panel(f"[bold green]Success![/bold green] Audiobook saved to: [underline]{output_path}[/underline]"))

async def main() -> int:
    load_dotenv()
    
    parser = argparse.ArgumentParser(description="Mistral-TTS-Booksmith CLI")
    parser.add_argument("--text", type=str, required=False, help="Path to input text file")
    parser.add_argument("--voice", type=str, required=False, help="Path to reference voice sample")
    parser.add_argument("--output", type=str, required=False, help="Path to output audiobook file")
    parser.add_argument("--api-key", type=str, required=False, help="Mistral AI API Key (overrides MISTRAL_API_KEY in .env)")
    parser.add_argument("--engine", type=str, default="mistral", choices=["mistral", "openai"], help="TTS engine to use")
    parser.add_argument("--openai-key", type=str, required=False, help="OpenAI API Key (overrides OPENAI_API_KEY in .env)")
    parser.add_argument("--tui", action="store_true", help="Launch the TUI")
    parser.add_argument("--source-lang", type=str, required=False, help="Source language of the input text")
    parser.add_argument("--target-lang", type=str, required=False, help="Target language to translate the text into")

    args = parser.parse_args()
    
    mistral_key = args.api_key or os.getenv("MISTRAL_API_KEY")
    openai_key = args.openai_key or os.getenv("OPENAI_API_KEY")

    if args.tui:
        from src.tui import BooksmithTUI
        app = BooksmithTUI()
        await app.run_async()
        return 0

    # Update arguments validation
    if not args.text or not args.output:
        parser.error("The following arguments are required if --tui is not used: --text, --output")
        
    if args.engine == "openai":
        if not openai_key:
            parser.error("OpenAI API key is required when using the openai engine. Use --openai-key or set OPENAI_API_KEY.")
    elif args.engine == "mistral":
        if not mistral_key:
            parser.error("Mistral API key is required when using the mistral engine. Use --api-key or set MISTRAL_API_KEY.")

    try:
        cli = BooksmithCLI(api_key=mistral_key.strip() if mistral_key else "")
        await cli.run(
            Path(args.text.strip()), 
            Path(args.voice.strip() if args.voice else ""), 
            Path(args.output.strip()),
            source_lang=args.source_lang.strip() if args.source_lang else None,
            target_lang=args.target_lang.strip() if args.target_lang else None,
            engine=args.engine,
            openai_key=openai_key
        )
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
