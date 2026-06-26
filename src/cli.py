import asyncio
import argparse
import json
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
from src.api.mistral_client import MistralTTSClient
from src.api.factory import get_tts_client
from src.core.audio_compiler import AudioCompiler

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
        self.cache_dir = Path("storage/cache")
        self.manifest_path = self.cache_dir / "manifest.json"
        
        # Ensure directories exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def load_manifest(self) -> dict:
        if self.manifest_path.exists():
            with open(self.manifest_path, "r") as f:
                return json.load(f)
        return {"chunks": [], "completed": []}

    def save_manifest(self, manifest: dict):
        with open(self.manifest_path, "w") as f:
            json.dump(manifest, f, indent=4)

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

        # Resolve the correct TTS API key and get client
        tts_api_key = openai_key if engine == "openai" else self.api_key
        if not tts_api_key:
            raise ValueError(f"API key is required for the selected engine ({engine}).")
        
        client = get_tts_client(engine, tts_api_key)

        # 0. Translate text if target language is specified
        if target_lang:
            if not self.api_key:
                raise ValueError("Mistral API key is required for translation.")
            source = source_lang or "English"
            with console.status(f"[bold blue]Translating text from {source} to {target_lang}..."):
                translation_client = MistralTTSClient(api_key=self.api_key)
                text_path = await translation_client.translate_file(text_path, source, target_lang)
                logger.info(f"Translation completed. Translated file: {text_path}")

        # 1. Read input text
        with console.status("[bold green]Reading input text..."):
            from src.core.epub_parser import read_input_text
            text = read_input_text(text_path)
            # 2. Split text
            chunks = self.splitter.split(text)
            logger.info(f"Text split into {len(chunks)} semantic chunks.")

        # 3. Configure voice
        voice_str = str(voice_path).strip() if voice_path else ""
        voice_provided = bool(voice_str and voice_str != ".")

        if engine == "openai":
            if voice_provided and voice_path.exists():
                raise ValueError("OpenAI TTS does not support voice cloning. Please select an OpenAI preset voice instead.")
            voice_id = voice_str if voice_provided else "alloy"
            client.set_voice_id(voice_id)
        elif engine == "mistral":
            if voice_provided and voice_path.exists():
                with console.status("[bold cyan]Cloning voice profile..."):
                    await client.clone_voice(voice_path)
                    logger.info("Voice profile cloned successfully.")
            else:
                voice_id = voice_str if voice_provided else "en_paul_neutral"
                client.set_voice_id(voice_id)

        # 4. Process chunks with progress bar
        manifest = self.load_manifest()
        manifest["chunks"] = chunks
        
        chunk_files = []
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            TimeRemainingColumn(),
            console=console
        ) as progress:
            task = progress.add_task("[cyan]Generating audio chunks...", total=len(chunks))
            
            for i, chunk in enumerate(chunks):
                chunk_filename = f"chunk_{i:04d}.mp3"
                chunk_path = self.cache_dir / chunk_filename
                chunk_files.append(chunk_path)

                if chunk_filename in manifest["completed"]:
                    progress.advance(task)
                    continue

                await client.generate_audio(chunk, chunk_path)
                manifest["completed"].append(chunk_filename)
                self.save_manifest(manifest)
                progress.advance(task)

        # 5. Compile final audiobook
        with console.status("[bold yellow]Compiling final audiobook..."):
            self.compiler.compile(chunk_files, output_path)
            
        console.print(Panel(f"[bold green]Success![/bold green] Audiobook saved to: [underline]{output_path}[/underline]"))

async def main():
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
        return

    # Update arguments validation
    if not args.text or not args.output:
        parser.error("The following arguments are required if --tui is not used: --text, --output")
        
    if args.engine == "openai":
        if not openai_key:
            parser.error("OpenAI API key is required when using the openai engine. Use --openai-key or set OPENAI_API_KEY.")
    elif args.engine == "mistral":
        if not mistral_key:
            parser.error("Mistral API key is required when using the mistral engine. Use --api-key or set MISTRAL_API_KEY.")

    cli = BooksmithCLI(api_key=mistral_key.strip() if mistral_key else "")
    try:
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

if __name__ == "__main__":
    asyncio.run(main())
