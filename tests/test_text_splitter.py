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

def test_text_splitter_srt():
    splitter = TextSplitter()
    srt_content = """1
00:00:01,000 --> 00:00:04,000
Hello, world!

2
00:00:05,000 --> 00:00:08,000
This is a subtitle.
And a second line.
"""
    chunks = splitter.split(srt_content)
    # The text should be normalized and timings omitted
    assert chunks == ["Hello, world! This is a subtitle. And a second line."]

