import pytest
from pathlib import Path
from src.cli import BooksmithCLI

@pytest.mark.anyio
async def test_cli_validation_openai_cloning(tmp_path):
    # Create a dummy voice file to ensure it exists
    dummy_voice = tmp_path / "sample.mp3"
    dummy_voice.write_bytes(b"dummy")
    
    text_path = tmp_path / "text.txt"
    text_path.write_text("Hello")
    output_path = tmp_path / "output.mp3"
    
    cli = BooksmithCLI(api_key="mistral-key")
    with pytest.raises(ValueError) as excinfo:
        await cli.run(
            text_path=text_path,
            voice_path=dummy_voice,
            output_path=output_path,
            engine="openai",
            openai_key="openai-key"
        )
    assert "OpenAI TTS does not support voice cloning" in str(excinfo.value)

@pytest.mark.anyio
async def test_cli_validation_missing_key(tmp_path):
    text_path = tmp_path / "text.txt"
    text_path.write_text("Hello")
    output_path = tmp_path / "output.mp3"
    
    cli = BooksmithCLI(api_key="mistral-key")
    with pytest.raises(ValueError):
        await cli.run(
            text_path=text_path,
            voice_path=Path("alloy"),
            output_path=output_path,
            engine="openai",
            openai_key=None
        )


@pytest.mark.anyio
async def test_cli_pre_compilation_invalid_chunk_raises_runtime_error(tmp_path):
    from unittest.mock import AsyncMock, MagicMock, patch

    text_path = tmp_path / "text.txt"
    text_path.write_text("Sentence one. Sentence two.")
    output_path = tmp_path / "output.mp3"

    cli = BooksmithCLI(api_key="mistral-key")
    cli.cache_dir = tmp_path / "cache"
    cli.cache_dir.mkdir(parents=True, exist_ok=True)

    with patch("src.cli.get_tts_client") as mock_get_client:
        mock_client = AsyncMock()
        mock_client.set_voice_id = MagicMock()
        # Mock generate_audio to create a file smaller than 100 bytes
        async def fake_generate(text, path):
            Path(path).write_bytes(b"small")
        mock_client.generate_audio = AsyncMock(side_effect=fake_generate)
        mock_get_client.return_value = mock_client

        with pytest.raises(RuntimeError, match="Missing or invalid chunk audio file before compilation"):
            await cli.run(
                text_path=text_path,
                voice_path=Path(""),
                output_path=output_path,
                engine="mistral"
            )


@pytest.mark.anyio
async def test_cli_cache_isolation_and_chunk_mismatch_check(tmp_path):
    import json
    import hashlib
    from unittest.mock import AsyncMock, MagicMock, patch

    text_path = tmp_path / "text.txt"
    text_path.write_text("Unique sentence for caching.")
    output_path = tmp_path / "output.mp3"

    cli = BooksmithCLI(api_key="mistral-key")
    cli.cache_dir = tmp_path / "cache"

    generated_texts = []
    async def fake_generate(text, path):
        generated_texts.append(text)
        Path(path).write_bytes(b"dummy valid audio content " * 10)

    with patch("src.cli.get_tts_client") as mock_get_client, \
         patch.object(cli.compiler, "compile") as mock_compile:
        mock_client = AsyncMock()
        mock_client.set_voice_id = MagicMock()
        mock_client.generate_audio = AsyncMock(side_effect=fake_generate)
        mock_get_client.return_value = mock_client
        mock_compile.return_value = {"output_duration": 5.0, "expected_duration": 5.0}

        voice_path = Path("")
        await cli.run(
            text_path=text_path,
            voice_path=voice_path,
            output_path=output_path,
            engine="mistral"
        )

        expected_raw = f"Unique sentence for caching.{str(voice_path).strip()}"
        expected_hash = hashlib.sha256(expected_raw.encode("utf-8")).hexdigest()
        assert cli.cache_dir.name == expected_hash
        assert cli.manifest_path.exists()
        manifest_data = json.loads(cli.manifest_path.read_text())
        assert manifest_data["completed"] == ["chunk_0000.mp3"]
        assert manifest_data["chunks"] == ["Unique sentence for caching."]
        assert len(generated_texts) == 1

        # Second run with SAME text -> should hit cache, NOT regenerate
        generated_texts.clear()
        await cli.run(
            text_path=text_path,
            voice_path=Path(""),
            output_path=output_path,
            engine="mistral"
        )
        assert len(generated_texts) == 0

        # Now test chunk mismatch: change manifest["chunks"] to different text
        manifest_data["chunks"] = ["Different sentence in manifest."]
        cli.manifest_path.write_text(json.dumps(manifest_data))

        # Third run with mismatched chunk -> must re-generate because chunk changed!
        generated_texts.clear()
        await cli.run(
            text_path=text_path,
            voice_path=Path(""),
            output_path=output_path,
            engine="mistral"
        )
        assert len(generated_texts) == 1


@pytest.mark.anyio
async def test_cli_cache_isolation_between_different_books(tmp_path):
    """Ensure two different books with different text never share cached chunks or collide in cache directories."""
    import json
    from unittest.mock import AsyncMock, MagicMock, patch

    book_a_path = tmp_path / "book_a.txt"
    book_a_path.write_text("Book A: Call me Ishmael.")

    book_b_path = tmp_path / "book_b.txt"
    book_b_path.write_text("Book B: It was the best of times.")

    output_a = tmp_path / "book_a.mp3"
    output_b = tmp_path / "book_b.mp3"

    cache_root = tmp_path / "cache"

    generated_chunks_a = []
    generated_chunks_b = []

    async def fake_generate_audio(chunk, path):
        path = Path(path)
        path.write_bytes(b"VALID_AUDIO_CHUNK_DATA_" * 10)
        if "Book A" in chunk:
            generated_chunks_a.append((chunk, path))
        else:
            generated_chunks_b.append((chunk, path))

    cli_a = BooksmithCLI(api_key="mistral-key")
    cli_a.cache_dir = cache_root

    with patch("src.cli.get_tts_client") as mock_get_client, \
         patch.object(cli_a.compiler, "compile") as mock_compile:
        mock_client = AsyncMock()
        mock_client.set_voice_id = MagicMock()
        mock_client.generate_audio = AsyncMock(side_effect=fake_generate_audio)
        mock_get_client.return_value = mock_client
        mock_compile.return_value = {"output_duration": 5.0, "expected_duration": 5.0}

        # 1. Process Book A
        await cli_a.run(
            text_path=book_a_path,
            voice_path=Path("en_paul_neutral"),
            output_path=output_a,
            engine="mistral"
        )
        cache_dir_a = cli_a.cache_dir
        manifest_a_path = cli_a.manifest_path

        assert cache_dir_a.exists()
        assert len(generated_chunks_a) == 1
        assert generated_chunks_a[0][0] == "Book A: Call me Ishmael."
        assert (cache_dir_a / "chunk_0000.mp3").exists()

    # 2. Process Book B with the same voice (new CLI invocation)
    cli_b = BooksmithCLI(api_key="mistral-key")
    cli_b.cache_dir = cache_root

    with patch("src.cli.get_tts_client") as mock_get_client, \
         patch.object(cli_b.compiler, "compile") as mock_compile:
        mock_client = AsyncMock()
        mock_client.set_voice_id = MagicMock()
        mock_client.generate_audio = AsyncMock(side_effect=fake_generate_audio)
        mock_get_client.return_value = mock_client
        mock_compile.return_value = {"output_duration": 5.0, "expected_duration": 5.0}

        await cli_b.run(
            text_path=book_b_path,
            voice_path=Path("en_paul_neutral"),
            output_path=output_b,
            engine="mistral"
        )
        cache_dir_b = cli_b.cache_dir
        manifest_b_path = cli_b.manifest_path

        assert cache_dir_b.exists()
        # Ensure separate cache subdirectories were used!
        assert cache_dir_a != cache_dir_b
        assert manifest_a_path != manifest_b_path

        # Ensure Book B generated its own chunk and did NOT reuse Book A's chunk
        assert len(generated_chunks_b) == 1
        assert generated_chunks_b[0][0] == "Book B: It was the best of times."
        assert (cache_dir_b / "chunk_0000.mp3").exists()

        # Check manifests are completely separate
        manifest_a = json.loads(manifest_a_path.read_text())
        manifest_b = json.loads(manifest_b_path.read_text())
        assert manifest_a["chunks"] == ["Book A: Call me Ishmael."]
        assert manifest_b["chunks"] == ["Book B: It was the best of times."]

    # 3. Rerun Book A -> should hit Book A's cache without generating any audio
    generated_chunks_a.clear()
    generated_chunks_b.clear()

    cli_a2 = BooksmithCLI(api_key="mistral-key")
    cli_a2.cache_dir = cache_root

    with patch("src.cli.get_tts_client") as mock_get_client, \
         patch.object(cli_a2.compiler, "compile") as mock_compile:
        mock_client = AsyncMock()
        mock_client.set_voice_id = MagicMock()
        mock_client.generate_audio = AsyncMock(side_effect=fake_generate_audio)
        mock_get_client.return_value = mock_client
        mock_compile.return_value = {"output_duration": 5.0, "expected_duration": 5.0}

        await cli_a2.run(
            text_path=book_a_path,
            voice_path=Path("en_paul_neutral"),
            output_path=output_a,
            engine="mistral"
        )
        assert len(generated_chunks_a) == 0
        assert len(generated_chunks_b) == 0

    # 4. Run Book A with different voice -> must yield a distinct cache directory
    cli_a_voice2 = BooksmithCLI(api_key="mistral-key")
    cli_a_voice2.cache_dir = cache_root

    with patch("src.cli.get_tts_client") as mock_get_client, \
         patch.object(cli_a_voice2.compiler, "compile") as mock_compile:
        mock_client = AsyncMock()
        mock_client.set_voice_id = MagicMock()
        mock_client.generate_audio = AsyncMock(side_effect=fake_generate_audio)
        mock_get_client.return_value = mock_client
        mock_compile.return_value = {"output_duration": 5.0, "expected_duration": 5.0}

        await cli_a_voice2.run(
            text_path=book_a_path,
            voice_path=Path("fr_marie_neutral"),
            output_path=output_a,
            engine="mistral"
        )
        cache_dir_a_voice2 = cli_a_voice2.cache_dir
        assert cache_dir_a_voice2 != cache_dir_a
        assert cache_dir_a_voice2 != cache_dir_b


@pytest.mark.anyio
async def test_cli_sequential_runs_same_instance_no_cache_nesting(tmp_path):
    """Ensure multiple sequential .run() calls on the same CLI instance do not nest cache directories."""
    from unittest.mock import AsyncMock, MagicMock, patch

    book1 = tmp_path / "book1.txt"
    book1.write_text("First book text.")
    book2 = tmp_path / "book2.txt"
    book2.write_text("Second book text with different words.")

    out1 = tmp_path / "out1.mp3"
    out2 = tmp_path / "out2.mp3"

    cli = BooksmithCLI(api_key="mistral-key")
    cli.cache_dir = tmp_path / "cache"

    async def fake_gen(text, path):
        Path(path).write_bytes(b"VALID_CHUNK_AUDIO_DATA_" * 10)

    with patch("src.cli.get_tts_client") as mock_get_client, \
         patch.object(cli.compiler, "compile") as mock_compile:
        mock_client = AsyncMock()
        mock_client.set_voice_id = MagicMock()
        mock_client.generate_audio = AsyncMock(side_effect=fake_gen)
        mock_get_client.return_value = mock_client
        mock_compile.return_value = {"output_duration": 5.0, "expected_duration": 5.0}

        # Run 1
        await cli.run(text_path=book1, voice_path=Path("alloy"), output_path=out1, engine="openai", openai_key="key")
        cache1 = cli.cache_dir

        # Run 2 on same CLI instance
        await cli.run(text_path=book2, voice_path=Path("alloy"), output_path=out2, engine="openai", openai_key="key")
        cache2 = cli.cache_dir

        assert cache1 != cache2
        assert cache1.parent == cli.base_cache_dir
        assert cache2.parent == cli.base_cache_dir
        # Ensure cache2 is not nested inside cache1
        assert not cache2.is_relative_to(cache1)
        assert not cache1.is_relative_to(cache2)




