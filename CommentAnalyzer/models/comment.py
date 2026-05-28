from enum import Enum

class SuspicionLevel(Enum):
    VERY_LOW = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    VERY_HIGH = 5



class Comment:
    def __init__(self, id: str, parent_id: str, text: str, author: str, created_utc: float):
        self.id = id
        self.parent_id = parent_id
        self.text = text
        self.author = author
        self.created_utc = created_utc

        self.cleaned_text = self._normalize_text(text)
        self.char_count = len(self.cleaned_text)
        self.word_count = len(self.cleaned_text.split())

    def _normalize_text(self, raw_text):
        if not raw_text:
            return ''
        return raw_text.strip().lower()


    def get_author(self) -> str:
        return self.author

    def get_parent_id(self) -> str:
        return self.parent_id
