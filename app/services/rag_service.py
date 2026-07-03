from __future__ import annotations

from collections import Counter
from math import sqrt
import re


class RagService:
    def retrieve(self, question: str, documents: list[dict], top_k: int = 3) -> list[dict]:
        chunks = self._chunk_documents(documents)
        if not chunks:
            return []

        query_vector = self._embed(question)
        ranked = []
        for chunk in chunks:
            score = self._cosine(query_vector, self._embed(chunk["text"]))
            score += self._metadata_boost(question, chunk)
            if score > 0:
                result = dict(chunk)
                result["score"] = round(score, 4)
                ranked.append(result)

        return sorted(ranked, key=lambda item: item["score"], reverse=True)[:top_k]

    def build_answer(self, question: str, results: list[dict]) -> str:
        if not results:
            return "I could not find a relevant meeting document for that question."

        best = results[0]
        doc = best["document"]
        issue_lines = self._extract_section_lines(doc["content"], "Issues Addressed")
        action_lines = self._extract_section_lines(doc["content"], "Action Items")

        if not issue_lines and not action_lines:
            policy_lines = self._extract_section_lines(doc["content"], "Policy Rules")
            troubleshooting_lines = self._extract_section_lines(doc["content"], "Troubleshooting Guidance")
            responsibilities_lines = self._extract_section_lines(doc["content"], "Responsibilities")

            section_lines = policy_lines or troubleshooting_lines or responsibilities_lines
            if section_lines:
                return f"From {doc['title']}: {'; '.join(section_lines[:3])}"

            return f"From {doc['title']}: {best['text']}"

        issue_text = "; ".join(issue_lines[:2]) if issue_lines else best["text"]
        action_text = "; ".join(action_lines[:2]) if action_lines else "No explicit action item found."

        return (
            f"From {doc['title']} on {doc['date']}: {issue_text} "
            f"Recommended follow-up: {action_text}"
        )

    def extract_action_summary(self, document: dict) -> str:
        action_lines = self._extract_section_lines(document["content"], "Action Items")
        if action_lines:
            return action_lines[0][:80]

        issue_lines = self._extract_section_lines(document["content"], "Issues Addressed")
        if issue_lines:
            return f"Follow up: {issue_lines[0]}"[:80]

        return f"Follow up from {document['title']}"[:80]

    def _chunk_documents(self, documents: list[dict]) -> list[dict]:
        chunks = []
        for doc in documents:
            sections = re.split(r"\n(?=## )", doc["content"])
            for index, section in enumerate(sections):
                text = self._clean_text(section)
                if not text:
                    continue
                chunks.append(
                    {
                        "chunk_id": f"{doc['id']}::chunk-{index + 1}",
                        "text": text,
                        "document": doc,
                    }
                )
        return chunks

    def _embed(self, text: str) -> Counter:
        tokens = re.findall(r"[a-z0-9-]+", text.lower())
        stop_words = {
            "a",
            "an",
            "and",
            "are",
            "as",
            "for",
            "from",
            "in",
            "is",
            "it",
            "of",
            "on",
            "the",
            "to",
            "what",
            "with",
        }
        return Counter(token for token in tokens if token not in stop_words)

    def _cosine(self, left: Counter, right: Counter) -> float:
        if not left or not right:
            return 0.0

        shared = set(left) & set(right)
        numerator = sum(left[token] * right[token] for token in shared)
        left_norm = sqrt(sum(value * value for value in left.values()))
        right_norm = sqrt(sum(value * value for value in right.values()))

        if left_norm == 0 or right_norm == 0:
            return 0.0
        return numerator / (left_norm * right_norm)

    def _extract_section_lines(self, content: str, section_name: str) -> list[str]:
        pattern = rf"## {re.escape(section_name)}\s+(.*?)(?=\n## |\Z)"
        match = re.search(pattern, content, flags=re.DOTALL)
        if not match:
            return []

        lines = []
        for line in match.group(1).splitlines():
            cleaned = line.strip().lstrip("- ").strip()
            if cleaned:
                lines.append(cleaned)
        return lines

    def _clean_text(self, text: str) -> str:
        lines = []
        for line in text.splitlines():
            cleaned = line.strip()
            if cleaned:
                lines.append(cleaned.lstrip("#").strip())
        return " ".join(lines)

    def _metadata_boost(self, question: str, chunk: dict) -> float:
        question_text = question.lower()
        document = chunk["document"]
        title = document["title"].lower()
        content = document["content"].lower()
        boost = 0.0

        query_terms = set(self._embed(question).keys())
        title_terms = set(self._embed(title).keys())
        if query_terms and title_terms:
            boost += 0.08 * len(query_terms & title_terms)

        for phrase in self._candidate_phrases(question_text):
            if phrase in title:
                boost += 0.4
            elif phrase in content:
                boost += 0.2

        if any(keyword in question_text for keyword in ["who is", "employee", "profile"]):
            if "employee profile" in content or "role:" in content:
                boost += 0.5

        if "policy" in question_text and "policy" in title:
            boost += 0.4

        return boost

    def _candidate_phrases(self, question_text: str) -> list[str]:
        words = [
            word
            for word in re.findall(r"[a-z0-9-]+", question_text)
            if word not in {"what", "who", "is", "the", "a", "an", "for", "about"}
        ]
        phrases = []
        for size in range(2, min(5, len(words)) + 1):
            for index in range(0, len(words) - size + 1):
                phrases.append(" ".join(words[index : index + size]))
        return phrases
