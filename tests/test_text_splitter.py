import pytest
from src.core.text_splitter import TextSplitter

def test_text_splitter_basic():
    splitter = TextSplitter(max_chars=50)
    text = "This is a sentence. This is another sentence. Short one."
    chunks = splitter.split(text)
    assert len(chunks) > 0
    for chunk in chunks:
        assert len(chunk) <= 50

def test_text_splitter_long_sentence():
    splitter = TextSplitter(max_chars=20)
    text = "This is an extremely long sentence that exceeds the limit."
    chunks = splitter.split(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 20

def test_text_splitter_empty():
    splitter = TextSplitter()
    assert splitter.split("") == []
