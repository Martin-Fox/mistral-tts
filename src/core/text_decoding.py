"""Strict decoding: BOM/declaration or an explicit plain-text encoding, never guessing."""
import codecs
import os
import re


def decode_text(data: bytes, encoding=None, *, markup=False):
    selected = encoding if encoding is not None else os.getenv('INPUT_TEXT_ENCODING', 'auto')
    if markup:
        selected = 'auto'
        declaration = re.search(rb'^\s*<\?xml[^>]*encoding\s*=\s*[\"\x27]([^\"\x27]+)', data[:512], re.I)
        meta = re.search(rb'<meta\b[^>]*charset\s*=\s*[\"\x27]?\s*([A-Za-z0-9._-]+)', data[:4096], re.I)
        if declaration or meta:
            selected = (declaration or meta).group(1).decode('ascii')
    for prefix, codec in ((codecs.BOM_UTF32_LE, 'utf-32'), (codecs.BOM_UTF32_BE, 'utf-32'),
                          (codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16'),
                          (codecs.BOM_UTF8, 'utf-8-sig')):
        if data.startswith(prefix):
            selected = codec
            break
    if selected == 'auto':
        selected = 'utf-8'
    try:
        text = data.decode(selected, errors='strict')
    except (UnicodeError, LookupError):
        raise ValueError('Cannot decode input without losing characters; convert to UTF-8 or set INPUT_TEXT_ENCODING') from None
    if '\x00' in text:
        raise ValueError('Input contains NUL characters; check its encoding or convert to UTF-8')
    return text
