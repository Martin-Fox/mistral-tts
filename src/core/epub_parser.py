import zipfile
import logging
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
import urllib.parse
from src.core.text_decoding import decode_text
from src.core.resource_limits import ResourceLimits, ResourceLimitExceeded, check_text

logger = logging.getLogger(__name__)

class HTMLTextExtractor(HTMLParser):
    """
    Parser to extract visible text from XHTML/HTML chapters.
    Preserves structural line breaks for semantic chunking.
    """
    def __init__(self):
        super().__init__()
        self.result = []
        self.ignored_tags = {"style", "script", "head", "title", "meta", "link"}
        self.current_tag = ""
        self.tag_stack = []

    def handle_starttag(self, tag, attrs):
        if tag not in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.tag_stack.append(tag)
        self.current_tag = self.tag_stack[-1] if self.tag_stack else ""
        # Add newlines before block-level elements
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "br", "li", "tr", "blockquote"}:
            self.result.append("\n")

    def handle_endtag(self, tag):
        if tag in self.tag_stack:
            index = len(self.tag_stack) - 1 - self.tag_stack[::-1].index(tag)
            del self.tag_stack[index:]
        self.current_tag = self.tag_stack[-1] if self.tag_stack else ""
        # Add newlines after block-level elements
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote"}:
            self.result.append("\n")

    def handle_data(self, data):
        if not any(tag in self.ignored_tags for tag in self.tag_stack):
            self.result.append(data)

    def get_text(self) -> str:
        raw_text = "".join(self.result)
        # Clean up excessive newlines and whitespace
        lines = []
        for line in raw_text.splitlines():
            line = line.strip()
            if line:
                lines.append(line)
        return "\n\n".join(lines)

def strip_namespaces(xml_content: bytes) -> str:
    """
    Strips XML namespaces and tag prefixes to simplify parsing.
    """
    try:
        root = ET.fromstring(xml_content)
    except (ET.ParseError, LookupError, UnicodeError) as error:
        raise ValueError("Invalid EPUB XML metadata or encoding") from error
    for element in root.iter():
        if isinstance(element.tag, str):
            element.tag = element.tag.split('}')[-1]
    return ET.tostring(root, encoding='unicode')


def extract_text_from_epub(epub_path: Path) -> str:
    """
    Extracts and merges all text content from an EPUB file in its correct reading order
    using only Python standard libraries.
    """
    if not zipfile.is_zipfile(epub_path):
        raise ValueError("Invalid EPUB file: Not a zip archive.")

    limits = ResourceLimits.from_env()
    if epub_path.stat().st_size > limits.max_text_upload_bytes:
        raise ResourceLimitExceeded("Input exceeds MAX_TEXT_UPLOAD_BYTES")
    with zipfile.ZipFile(epub_path, "r") as z:
        entries = z.infolist()
        if len(entries) > limits.max_epub_entries:
            raise ResourceLimitExceeded("EPUB exceeds MAX_EPUB_ENTRIES")
        if any(entry.file_size > limits.max_epub_entry_bytes for entry in entries):
            raise ResourceLimitExceeded("EPUB element exceeds MAX_EPUB_ENTRY_BYTES")
        if sum(entry.file_size for entry in entries) > limits.max_epub_bytes:
            raise ResourceLimitExceeded("EPUB exceeds MAX_EPUB_BYTES after decompression")
        consumed = 0
        def read_member(name):
            nonlocal consumed
            budget = min(limits.max_epub_entry_bytes, limits.max_epub_bytes - consumed)
            with z.open(name) as stream:
                data = stream.read(budget + 1)
            if len(data) > budget:
                raise ResourceLimitExceeded("EPUB decompression budget exceeded")
            consumed += len(data)
            return data
        # 1. Read container.xml to locate the OPF file
        try:
            container_xml = read_member("META-INF/container.xml")
        except KeyError:
            raise ValueError("Invalid EPUB file: Missing META-INF/container.xml")

        container_str = strip_namespaces(container_xml)
        root = ET.fromstring(container_str)
        
        rootfile_elem = root.find(".//rootfile")
        if rootfile_elem is None or "full-path" not in rootfile_elem.attrib:
            raise ValueError("Invalid EPUB file: Could not find rootfile in container.xml")

        opf_path_str = rootfile_elem.attrib["full-path"]
        opf_path = PurePosixPath(opf_path_str)
        opf_dir = opf_path.parent
        
        # 2. Read and parse the OPF file
        try:
            opf_content = read_member(opf_path_str)
        except KeyError:
            raise ValueError(f"Invalid EPUB file: Missing OPF file at {opf_path_str}")

        opf_str = strip_namespaces(opf_content)
        opf_root = ET.fromstring(opf_str)
        
        # Map manifest items (id -> href)
        manifest_elem = opf_root.find("manifest")
        if manifest_elem is None:
            raise ValueError("Invalid EPUB file: Missing manifest in OPF")
                
        manifest = {}
        for item in manifest_elem:
            if item.tag == "item":
                item_id = item.attrib.get("id")
                item_href = item.attrib.get("href")
                if item_id and item_href:
                    manifest[item_id] = item_href

        # Extract spine items in reading order
        spine_elem = opf_root.find("spine")
        if spine_elem is None:
            raise ValueError("Invalid EPUB file: Missing spine in OPF")

        spine = []
        for itemref in spine_elem:
            if itemref.tag == "itemref":
                idref = itemref.attrib.get("idref")
                if not idref:
                    raise ValueError("EPUB spine item is missing idref")
                spine.append(idref)

        # 3. Extract and parse HTML files in reading order
        full_text = []
        text_size = 0
        
        for item_id in spine:
            href = manifest.get(item_id)
            if not href:
                raise ValueError(f"EPUB spine references missing manifest item: {item_id}")
            href = href.split("#", 1)[0]
            
            # Reconstruct the internal path relative to the OPF file directory
            if opf_dir == Path(".") or not opf_dir.name:
                target_path = href
            else:
                target_path = (opf_dir / href).as_posix()
                
                # Normalize target_path (resolving double dots '../')
                parts = target_path.split('/')
                resolved_parts = []
                for part in parts:
                    if part == '..':
                        if resolved_parts:
                            resolved_parts.pop()
                    elif part != '.' and part:
                        resolved_parts.append(part)
                target_path = "/".join(resolved_parts)

            try:
                html_bytes = read_member(target_path)
            except KeyError:
                # Fallback: try un-escaping URL-encoded hrefs
                unescaped_path = urllib.parse.unquote(target_path)
                try:
                    html_bytes = read_member(unescaped_path)
                except KeyError:
                    raise ValueError(f"EPUB chapter is missing: {item_id} ({target_path})") from None

            # Parse and extract text from HTML content
            html_content = decode_text(html_bytes, markup=True)
            extractor = HTMLTextExtractor()
            extractor.feed(html_content)
            extracted_text = extractor.get_text()
            if extracted_text:
                text_size += len(extracted_text) + (2 if full_text else 0)
                if text_size > limits.max_text_chars:
                    raise ResourceLimitExceeded("Text exceeds MAX_TEXT_CHARS")
                full_text.append(extracted_text)

        if not full_text:
            raise ValueError("EPUB file contains no readable text content.")

        return "\n\n".join(full_text)

def extract_text_from_mobi(mobi_path: Path, encoding=None) -> str:
    """
    Extracts and merges all text content from an unencrypted MOBI file
    using the mobi library and our HTML parser.
    """
    import mobi
    import shutil

    if not mobi_path.exists():
        raise FileNotFoundError(f"MOBI file not found: {mobi_path}")

    if mobi_path.stat().st_size > ResourceLimits.from_env().max_text_upload_bytes:
        raise ResourceLimitExceeded("Input exceeds MAX_TEXT_UPLOAD_BYTES")
    tempdir = None
    try:
        # Extract MOBI to a temporary directory
        tempdir, filepath_str = mobi.extract(str(mobi_path))
        filepath = Path(filepath_str)
        
        if not filepath.exists():
            raise FileNotFoundError(f"Extracted MOBI content not found at {filepath_str}")

        limits = ResourceLimits.from_env()
        if filepath.stat().st_size > limits.max_epub_bytes:
            raise ResourceLimitExceeded("Extracted MOBI content exceeds MAX_EPUB_BYTES")
        suffix = filepath.suffix.lower()
        if suffix in {".html", ".xhtml", ".htm"}:
            html_content = decode_text(filepath.read_bytes(), markup=True)
            extractor = HTMLTextExtractor()
            extractor.feed(html_content)
            text = extractor.get_text()
        else:
            text = decode_text(filepath.read_bytes(), encoding)

        if not text.strip():
            raise ValueError("MOBI file contains no readable text content.")

        return check_text(text)
    except ResourceLimitExceeded:
        raise
    except Exception as e:
        logger.error(f"Failed to extract text from MOBI file {mobi_path}: {e}")
        raise ValueError(f"Failed to parse MOBI file: {e}")
    finally:
        # Clean up temporary directory
        if tempdir and Path(tempdir).exists():
            try:
                shutil.rmtree(tempdir)
            except Exception as e:
                logger.warning(f"Failed to delete temporary MOBI extraction directory {tempdir}: {e}")

def read_input_text(file_path: Path, encoding=None) -> str:
    """
    Reads the text content of a file. Supports .epub, .mobi, and defaults to plain text.
    Handles encoding issues robustly.
    """
    limits = ResourceLimits.from_env()
    if file_path.stat().st_size > limits.max_text_upload_bytes:
        raise ResourceLimitExceeded("Input exceeds MAX_TEXT_UPLOAD_BYTES")
    suffix = file_path.suffix.lower()
    if suffix == ".epub":
        return extract_text_from_epub(file_path)
    elif suffix == ".mobi":
        return extract_text_from_mobi(file_path, encoding=encoding)
    else:
        with file_path.open('rb') as stream:
            data = stream.read(limits.max_text_upload_bytes + 1)
        if len(data) > limits.max_text_upload_bytes:
            raise ResourceLimitExceeded("Input exceeds MAX_TEXT_UPLOAD_BYTES")
        return check_text(decode_text(data, encoding))
