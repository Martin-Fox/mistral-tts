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


def test_text_splitter_trailing_text_without_punctuation():
    splitter = TextSplitter(max_chars=60)
    text = "First complete sentence. Second sentence without ending punctuation"
    chunks = splitter.split(text)
    joined = " ".join(chunks)
    assert "First complete sentence." in joined
    assert "Second sentence without ending punctuation" in joined


def test_text_splitter_srt_without_index_numbers():
    splitter = TextSplitter()
    srt_content = """00:00:01,000 --> 00:00:04,000
First subtitle line.

00:00:05,000 --> 00:00:08,000
Second subtitle line.
Final trailing note without timing
"""
    chunks = splitter.split(srt_content)
    joined = " ".join(chunks)
    assert "First subtitle line." in joined
    assert "Second subtitle line." in joined
    assert "Final trailing note without timing" in joined


def test_text_splitter_trailing_quotes_and_dialogue():
    splitter = TextSplitter(max_chars=80)
    text = 'He said, "Here is a statement." Then whispered, "Trailing dialogue without a dot"'
    chunks = splitter.split(text)
    joined = " ".join(chunks)
    assert 'He said, "Here is a statement."' in joined
    assert '"Trailing dialogue without a dot"' in joined


def test_text_splitter_multiline_ellipsis():
    splitter = TextSplitter(max_chars=60)
    text = "First thought.\nSecond thought...\n...wait\n...final trailing conclusion..."
    chunks = splitter.split(text)
    joined = " ".join(chunks)
    assert "First thought." in joined
    assert "Second thought..." in joined
    assert "...wait" in joined
    assert "...final trailing conclusion..." in joined


def test_text_splitter_srt_irregular_numbering_and_trailing_blocks():
    splitter = TextSplitter()
    srt_content = """10
00:00:01,000 --> 00:00:03,000
Opening block with non-standard index.

99
00:00:04,000 --> 00:00:07,000
Second block out of order.

extra_tag
00:00:08,000 --> 00:00:11,000
Trailing subtitle block with alphanumeric identifier.
"""
    chunks = splitter.split(srt_content)
    joined = " ".join(chunks)
    assert "Opening block with non-standard index." in joined
    assert "Second block out of order." in joined
    assert "Trailing subtitle block with alphanumeric identifier." in joined


def test_text_splitter_srt_trailing_blank_lines():
    splitter = TextSplitter()
    srt_content = """1
00:00:01,000 --> 00:00:02,000
Block one.

2
00:00:03,000 --> 00:00:04,000
Block two.



"""
    chunks = splitter.split(srt_content)
    joined = " ".join(chunks)
    assert "Block one." in joined
    assert "Block two." in joined



