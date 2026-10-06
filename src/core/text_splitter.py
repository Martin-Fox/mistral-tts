import re
from typing import List

class TextSplitter:
    """
    Handles semantic text segmentation for long-form content.
    Splits text into chunks that respect maximum character limits while
    preserving sentence boundaries and semantic flow.
    """

    def __init__(self, max_chars: int = 1000):
        """
        Initialize the TextSplitter.

        Args:
            max_chars (int): The maximum number of characters allowed per chunk.
                             Mistral API typically has limits, and staying below
                             helps with stability.
        """
        self.max_chars = max_chars

    def _is_srt(self, text: str) -> bool:
        """
        Helper to detect if the text content follows the SubRip Subtitle (SRT) format.

        Args:
            text (str): Input text string.

        Returns:
            bool: True if input matches SRT structure, False otherwise.
        """
        if not text:
            return False
        cleaned = text.lstrip("\ufeff \t\r\n")
        return bool(re.match(r'^(\d+\s*\n)?\s*\d\d:\d\d:\d\d', cleaned))

    def extract_text_from_srt(self, srt_content: str) -> str:
        """
        Extracts and joins only the dialogue/text lines from an SRT file, omitting timing and cue indices.
        Handles UTF-8 BOM, variable newlines, and cues lacking standard timing arrows.

        Args:
            srt_content (str): Raw SRT subtitle content.

        Returns:
            str: Normalized dialogue text extracted across all subtitle cues.
        """
        if not srt_content or not srt_content.strip():
            return ""
        srt_content = srt_content.lstrip("\ufeff").replace("\r\n", "\n")
        raw_blocks = re.split(r'\n\s*\n+', srt_content.strip())
        text_pieces = []
        for raw_block in raw_blocks:
            lines = [line.strip() for line in raw_block.strip().split('\n') if line.strip()]
            if not lines:
                continue

            # Find the line with the timestamp arrow '-->'
            timing_idx = -1
            for idx, line in enumerate(lines):
                if '-->' in line:
                    timing_idx = idx
                    break

            if timing_idx != -1:
                # Text is all lines following the timing line
                content_lines = lines[timing_idx + 1:]
                if content_lines:
                    block_text = " ".join(content_lines).strip()
                    if block_text:
                        text_pieces.append(block_text)
            else:
                # No timing arrow found: if not an index number, preserve it as text
                non_index_lines = [line for line in lines if not line.isdigit()]
                if non_index_lines:
                    block_text = " ".join(non_index_lines).strip()
                    if block_text:
                        text_pieces.append(block_text)

        return " ".join(text_pieces).strip()

    def split(self, text: str) -> List[str]:
        """
        Splits the input text into a list of semantic chunks respecting max_chars.
        Automatically detects and extracts SRT subtitles, normalizes whitespace, splits
        at sentence boundaries, falls back to word boundaries when necessary, and preserves
        trailing unpunctuated text.

        Args:
            text (str): The raw input text or SRT string.

        Returns:
            List[str]: A list of text chunks each within character limits.
        """
        if not text or not text.strip():
            return []

        if self._is_srt(text):
            text = self.extract_text_from_srt(text)

        # Normalize whitespace without dropping trailing text lacking punctuation
        text = re.sub(r'\s+', ' ', text).strip()
        if not text:
            return []

        # Split into sentences using regex looking for punctuation followed by space
        sentences = re.split(r'(?<=[.!?])\s+', text)

        chunks = []
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # If a single sentence is longer than max_chars, split preserving words
            if len(sentence) > self.max_chars:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""

                words = sentence.split(" ")
                sub_chunk = ""
                for word in words:
                    if not word:
                        continue
                    if len(sub_chunk) + len(word) + 1 <= self.max_chars:
                        sub_chunk = f"{sub_chunk} {word}" if sub_chunk else word
                    else:
                        if sub_chunk:
                            chunks.append(sub_chunk.strip())
                        if len(word) > self.max_chars:
                            for i in range(0, len(word), self.max_chars):
                                chunks.append(word[i:i + self.max_chars])
                            sub_chunk = ""
                        else:
                            sub_chunk = word
                if sub_chunk and sub_chunk.strip():
                    chunks.append(sub_chunk.strip())
                continue

            # Check if adding the sentence would exceed the limit
            if len(current_chunk) + len(sentence) + 1 <= self.max_chars:
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence
            else:
                chunks.append(current_chunk.strip())
                current_chunk = sentence

        if current_chunk and current_chunk.strip():
            chunks.append(current_chunk.strip())

        return chunks

if __name__ == "__main__":
    # Quick test
    splitter = TextSplitter(max_chars=50)
    sample_text = "This is a sentence. This is another sentence that is quite long indeed. Short one."
    result = splitter.split(sample_text)
    for i, chunk in enumerate(result):
        print(f"Chunk {i+1}: {chunk}")
