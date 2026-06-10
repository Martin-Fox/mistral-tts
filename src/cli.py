import asyncio
import argparse
import json
import logging
from pathlib import Path
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeRemainingColumn
from rich.panel import Panel
from rich.logging import RichHandler
from src.core.text_splitter import TextSplitter
from src.api.mistral_client import MistralTTSClient
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
        self.splitter = TextSplitter()
        self.client = MistralTTSClient(api_key=api_key)
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

    async def run(self, text_path: Path, voice_path: Path, output_path: Path):
        console.print(Panel.fit("Mistral-TTS-Booksmith", style="bold magenta"))

        # 1. Read input text
        with console.status("[bold green]Reading input text..."):
            with open(text_path, "r") as f:
                text = f.read()
            # 2. Split text
            chunks = self.splitter.split(text)
            logger.info(f"Text split into {len(chunks)} semantic chunks.")

        # 3. Clone voice
        with console.status("[bold cyan]Cloning voice profile..."):
            await self.client.clone_voice(voice_path)
            logger.info("Voice profile cloned successfully.")

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

                await self.client.generate_audio(chunk, chunk_path)
                manifest["completed"].append(chunk_filename)
                self.save_manifest(manifest)
                progress.advance(task)

        # 5. Compile final audiobook
        with console.status("[bold yellow]Compiling final audiobook..."):
            self.compiler.compile(chunk_files, output_path)
            
        console.print(Panel(f"[bold green]Success![/bold green] Audiobook saved to: [underline]{output_path}[/underline]"))

async def main():
    parser = argparse.ArgumentParser(description="Mistral-TTS-Booksmith CLI")
    parser.add_argument("--text", type=str, required=False, help="Path to input text file")
    parser.add_argument("--voice", type=str, required=False, help="Path to reference voice sample")
    parser.add_argument("--output", type=str, required=False, help="Path to output audiobook file")
    parser.add_argument("--api-key", type=str, required=False, help="Mistral AI API Key")
    parser.add_argument("--tui", action="store_true", help="Launch the TUI")

    args = parser.parse_args()

    if args.tui:
        from src.tui import BooksmithTUI
        app = BooksmithTUI()
        await app.run_async()
        return

    if not all([args.text, args.voice, args.output, args.api_key]):
        parser.error("The following arguments are required if --tui is not used: --text, --voice, --output, --api-key")

    cli = BooksmithCLI(api_key=args.api_key)
    try:
        await cli.run(Path(args.text), Path(args.voice), Path(args.output))
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")

if __name__ == "__main__":
    asyncio.run(main())
