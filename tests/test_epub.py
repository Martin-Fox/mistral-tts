import pytest
import zipfile
import tempfile
from pathlib import Path
from src.core.epub_parser import extract_text_from_epub, read_input_text

def create_mock_epub(dest_path: Path, chapters: list[tuple[str, str]]):
    """
    Programmatically creates a valid mock EPUB zip file with the given chapters.
    """
    with zipfile.ZipFile(dest_path, "w") as z:
        # 1. Add container.xml
        container_xml = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""
        z.writestr("META-INF/container.xml", container_xml)

        # 2. Build content.opf (manifest & spine)
        manifest_items = []
        spine_items = []
        for i, (filename, _) in enumerate(chapters):
            item_id = f"chap_{i}"
            manifest_items.append(f'<item id="{item_id}" href="{filename}" media-type="application/xhtml+xml"/>')
            spine_items.append(f'<itemref idref="{item_id}"/>')

        manifest_str = "\n    ".join(manifest_items)
        spine_str = "\n    ".join(spine_items)

        opf_xml = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="bookid" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Test Book</dc:title>
  </metadata>
  <manifest>
    {manifest_str}
  </manifest>
  <spine toc="ncx">
    {spine_str}
  </spine>
</package>"""
        z.writestr("OEBPS/content.opf", opf_xml)

        # 3. Add chapter files
        for filename, content in chapters:
            z.writestr(f"OEBPS/{filename}", content)

def test_extract_text_from_epub():
    chapters = [
        ("chapter1.xhtml", "<html><head><title>C1</title></head><body><h1>Chapter 1</h1><p>This is the first paragraph.</p></body></html>"),
        ("chapter2.xhtml", "<html><body><h2>Chapter 2</h2><div>This is the second chapter.</div><p>Another paragraph.</p></body></html>"),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        epub_path = Path(tmpdir) / "test_book.epub"
        create_mock_epub(epub_path, chapters)

        text = extract_text_from_epub(epub_path)
        
        # Verify text content and reading order
        assert "Chapter 1" in text
        assert "This is the first paragraph." in text
        assert "Chapter 2" in text
        assert "This is the second chapter." in text
        assert "Another paragraph." in text
        
        # Verify paragraph spacing and tag stripping
        assert "<p>" not in text
        assert "<html>" not in text
        assert "Chapter 1\n\nThis is the first paragraph." in text
        
        # Verify read_input_text helper
        generic_text = read_input_text(epub_path)
        assert generic_text == text

def test_read_input_text_plain_text():
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = Path(tmpdir) / "test.txt"
        txt_path.write_text("Hello plain text world.", encoding="utf-8")
        
        text = read_input_text(txt_path)
        assert text == "Hello plain text world."
