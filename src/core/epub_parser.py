import zipfile
import re
import logging
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
import urllib.parse

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
        self.tag_stack.append(tag)
        self.current_tag = tag
        # Add newlines before block-level elements
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "br", "li", "tr", "blockquote"}:
            self.result.append("\n")

    def handle_endtag(self, tag):
        if self.tag_stack:
            self.tag_stack.pop()
        self.current_tag = self.tag_stack[-1] if self.tag_stack else ""
        # Add newlines after block-level elements
        if tag in {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote"}:
            self.result.append("\n")

    def handle_data(self, data):
        if self.current_tag not in self.ignored_tags:
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
    xml_str = xml_content.decode("utf-8", errors="ignore")
    # Remove default xmlns="..."
    xml_str = re.sub(r'\sxmlns="[^"]+"', '', xml_str)
    # Remove prefixed xmlns:prefix="..."
    xml_str = re.sub(r'\sxmlns:\w+="[^"]+"', '', xml_str)
    # Remove namespace prefixes from tags: <prefix:tag ...> to <tag ...>
    xml_str = re.sub(r'<[a-zA-Z0-9_]+:([a-zA-Z0-9_]+)', r'<\1', xml_str)
    # Remove namespace prefixes from closing tags: </prefix:tag> to </tag>
    xml_str = re.sub(r'</[a-zA-Z0-9_]+:([a-zA-Z0-9_]+)>', r'</\1>', xml_str)
    return xml_str

def extract_text_from_epub(epub_path: Path) -> str:
    """
    Extracts and merges all text content from an EPUB file in its correct reading order
    using only Python standard libraries.
    """
    if not zipfile.is_zipfile(epub_path):
        raise ValueError("Invalid EPUB file: Not a zip archive.")

    with zipfile.ZipFile(epub_path, "r") as z:
        # 1. Read container.xml to locate the OPF file
        try:
            container_xml = z.read("META-INF/container.xml")
        except KeyError:
            raise ValueError("Invalid EPUB file: Missing META-INF/container.xml")

        container_str = strip_namespaces(container_xml)
        root = ET.fromstring(container_str)
        
        rootfile_elem = root.find(".//rootfile")
        if rootfile_elem is None or "full-path" not in rootfile_elem.attrib:
            raise ValueError("Invalid EPUB file: Could not find rootfile in container.xml")

        opf_path_str = rootfile_elem.attrib["full-path"]
        opf_path = Path(opf_path_str)
        opf_dir = opf_path.parent
        
        # 2. Read and parse the OPF file
        try:
            opf_content = z.read(opf_path_str)
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
                if idref:
                    spine.append(idref)

        # 3. Extract and parse HTML files in reading order
        full_text = []
        
        for item_id in spine:
            href = manifest.get(item_id)
            if not href:
                continue
            
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
                html_bytes = z.read(target_path)
            except KeyError:
                # Fallback: try un-escaping URL-encoded hrefs
                unescaped_path = urllib.parse.unquote(target_path)
                try:
                    html_bytes = z.read(unescaped_path)
                except KeyError:
                    logger.warning(f"Could not find manifest item '{item_id}' at path '{target_path}' inside EPUB archive.")
                    continue

            # Parse and extract text from HTML content
            html_content = html_bytes.decode("utf-8", errors="ignore")
            extractor = HTMLTextExtractor()
            extractor.feed(html_content)
            extracted_text = extractor.get_text()
            if extracted_text:
                full_text.append(extracted_text)

        if not full_text:
            raise ValueError("EPUB file contains no readable text content.")

        return "\n\n".join(full_text)

def extract_text_from_mobi(mobi_path: Path) -> str:
    """
    Extracts and merges all text content from an unencrypted MOBI file
    using the mobi library and our HTML parser.
    """
    import mobi
    import shutil

    if not mobi_path.exists():
        raise FileNotFoundError(f"MOBI file not found: {mobi_path}")

    tempdir = None
    try:
        # Extract MOBI to a temporary directory
        tempdir, filepath_str = mobi.extract(str(mobi_path))
        filepath = Path(filepath_str)
        
        if not filepath.exists():
            raise FileNotFoundError(f"Extracted MOBI content not found at {filepath_str}")

        suffix = filepath.suffix.lower()
        if suffix in {".html", ".xhtml", ".htm"}:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                html_content = f.read()
            extractor = HTMLTextExtractor()
            extractor.feed(html_content)
            text = extractor.get_text()
        else:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()

        if not text.strip():
            raise ValueError("MOBI file contains no readable text content.")

        return text
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

def read_input_text(file_path: Path) -> str:
    """
    Reads the text content of a file. Supports .epub, .mobi, and defaults to plain text.
    Handles encoding issues robustly.
    """
    suffix = file_path.suffix.lower()
    if suffix == ".epub":
        return extract_text_from_epub(file_path)
    elif suffix == ".mobi":
        return extract_text_from_mobi(file_path)
    else:
        # Try reading as UTF-8 first, fallback to ignore errors if it fails
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()


