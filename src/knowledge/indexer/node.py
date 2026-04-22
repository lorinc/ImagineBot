"""node.py — Node dataclass: the single data model for the PageIndex tree."""

from dataclasses import dataclass, field


@dataclass
class Node:
    id: str
    level: int
    title: str
    content: str
    topics: str = ""
    is_preamble: bool = False
    children: list = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.content)

    def full_text(self, include_heading: bool = True) -> str:
        """Recursively: heading + direct content + all children full_text."""
        parts = []
        if include_heading and self.level > 0:
            parts.append(f"{'#' * self.level} {self.title}")
        if self.content:
            parts.append(self.content)
        for child in self.children:
            parts.append(child.full_text(include_heading=True))
        return "\n\n".join(p for p in parts if p)

    @property
    def full_text_char_count(self) -> int:
        return len(self.full_text())

    def is_leaf(self) -> bool:
        return not self.children

    def all_nodes(self) -> list:
        """Flat list: self (if non-root) + all descendants, depth-first."""
        result = []
        if self.level > 0:
            result.append(self)
        for child in self.children:
            result.extend(child.all_nodes())
        return result

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "level": self.level,
            "title": self.title,
            "content": self.content,
            "topics": self.topics,
            "is_preamble": self.is_preamble,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Node":
        children = [cls.from_dict(c) for c in d.get("children", [])]
        n = cls(
            id=d["id"],
            level=d["level"],
            title=d["title"],
            content=d["content"],
            topics=d.get("topics", ""),
            is_preamble=d.get("is_preamble", False),
        )
        n.children = children
        return n
