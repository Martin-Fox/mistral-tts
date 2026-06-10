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

    def split(self, text: str) -> List[str]:
        """
        Splits the input text into a list of semantic chunks.

        Args:
            text (str): The raw input text.

        Returns:
            List[str]: A list of text chunks.
        """
        if not text:
            return []

        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()

        # Split into sentences using a simple regex that looks for punctuation
        # followed by space or end of string.
        # This is a basic implementation and might need refinement for complex cases.
        sentences = re.split(r'(?<=[.!?])\s+', text)

        chunks = []
        current_chunk = ""

        for sentence in sentences:
            # If a single sentence is longer than max_chars, we have to split it.
            # This is a fallback to prevent blocking, though not ideal for TTS.
            if len(sentence) > self.max_chars:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                    current_chunk = ""
                
                # Naive split for extremely long sentences
                for i in range(0, len(sentence), self.max_chars):
                    chunks.append(sentence[i:i + self.max_chars].strip())
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

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

if __name__ == "__main__":
    # Quick test
    splitter = TextSplitter(max_chars=50)
    sample_text = "This is a sentence. This is another sentence that is quite long indeed. Short one."
    result = splitter.split(sample_text)
    for i, chunk in enumerate(result):
        print(f"Chunk {i+1}: {chunk}")
