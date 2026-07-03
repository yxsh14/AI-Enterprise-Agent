from __future__ import annotations

from collections import Counter
from math import sqrt
import re


class RagService:
    def retrieve(
        self,
        question: str,
        documents: list[dict],
        top_k: int = 3,
        resolved_date: str | None = None,
    ) -> list[dict]:
        chunks = self._chunk_documents(documents)
        if not chunks:
            return []

        # Include ISO date tokens so "03 July 2026" matches doc text "2026-07-03".
        query_text = question
        if resolved_date:
            query_text = f"{question} {resolved_date} {resolved_date.replace('-', ' ')}"

        query_vector = self._embed(query_text)
        ranked = []
        for chunk in chunks:
            score = self._cosine(query_vector, self._embed(chunk["text"]))
            score += self._metadata_boost(question, chunk, resolved_date=resolved_date)
            if score > 0:
                result = dict(chunk)
                result["score"] = round(score, 4)
                ranked.append(result)

        ranked = sorted(ranked, key=lambda item: item["score"], reverse=True)[:top_k]

        # When the user asked for a specific date we already filtered docs — never return empty.
        if not ranked and resolved_date and documents:
            return self.chunks_for_documents(documents)[:top_k]

        return ranked

    def chunks_for_documents(self, documents: list[dict]) -> list[dict]:
        """Return all section chunks for *documents* (used when date filter already narrowed scope)."""
        chunks = self._chunk_documents(documents)
        return [
            {**chunk, "score": 1.0}
            for chunk in chunks
            if chunk.get("text")
        ]

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
        for iso_date in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text.lower()):
            year, month, day = iso_date.split("-")
            tokens.extend([year, month, day, iso_date])

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

    def _metadata_boost(
        self, question: str, chunk: dict, resolved_date: str | None = None
    ) -> float:
        question_text = question.lower()
        document = chunk["document"]
        title = document["title"].lower()
        content = document["content"].lower()
        boost = 0.0

        if resolved_date and document.get("date") == resolved_date:
            boost += 2.0

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

    # ------------------------------------------------------------------
    # Index → individual meeting doc resolution (Step 3)
    # ------------------------------------------------------------------

    def resolve_meeting_from_index(
        self,
        question: str,
        results: list[dict],
        all_documents: list[dict],
        resolved_date: str | None,
    ) -> list[dict]:
        """If the top RAG result is the Meeting Log Index, swap it for the real meeting doc."""
        if not results:
            return results

        top_doc = results[0]["document"]
        if "meeting log index" not in top_doc.get("title", "").lower():
            return results

        # Try to find the individual meeting doc by resolved_date first
        if resolved_date:
            for doc in all_documents:
                if doc["date"] == resolved_date and "index" not in doc.get("title", "").lower():
                    re_ranked = self.retrieve(question, [doc])
                    if re_ranked:
                        return re_ranked

        # Fallback: parse index table for the date and find the matching doc
        if resolved_date:
            row = self.parse_index_row(top_doc.get("content", ""), resolved_date)
            if row:
                for doc in all_documents:
                    if (
                        row["live_doc_title"].lower() in doc.get("title", "").lower()
                        and "index" not in doc.get("title", "").lower()
                    ):
                        re_ranked = self.retrieve(question, [doc])
                        if re_ranked:
                            return re_ranked
                # If we found a row but no matching doc, return a synthetic chunk
                return self._build_row_chunk(row, top_doc)

        # Last resort: remove index and re-rank remaining docs
        non_index_docs = [
            d for d in all_documents if "index" not in d.get("title", "").lower()
        ]
        if non_index_docs:
            re_ranked = self.retrieve(question, non_index_docs)
            if re_ranked:
                return re_ranked

        return results

    def parse_index_row(self, content: str, target_date: str) -> dict | None:
        """Parse the Meeting Log Index table for a row matching *target_date*.

        Returns a dict with keys: date, live_doc_title, primary_issue, jira_action, priority.
        """
        for line in content.splitlines():
            if target_date not in line:
                continue
            # Index table rows use " | " as separator (from Confluence HTML→text conversion)
            parts = [part.strip() for part in line.split("|") if part.strip()]
            if len(parts) >= 4:
                return {
                    "date": target_date,
                    "live_doc_title": parts[1] if len(parts) > 1 else "",
                    "primary_issue": parts[2] if len(parts) > 2 else "",
                    "jira_action": parts[3] if len(parts) > 3 else "",
                    "priority": parts[4].strip() if len(parts) > 4 else "Medium",
                }
        return None

    def _build_row_chunk(self, row: dict, source_doc: dict) -> list[dict]:
        """Build a synthetic RAG chunk from a parsed index row."""
        text = (
            f"Meeting: {row['live_doc_title']} on {row['date']}. "
            f"Primary issue: {row['primary_issue']}. "
            f"Recommended Jira action: {row['jira_action']}."
        )
        if row.get("priority"):
            text += f" Priority: {row['priority']}."
        return [
            {
                "chunk_id": f"{source_doc['id']}::index-row-{row['date']}",
                "text": text,
                "document": source_doc,
                "score": 1.0,
            }
        ]

    def build_ticket_description(self, document: dict) -> str:
        """Short deterministic description for a Jira ticket from meeting context."""
        title = document.get("title", "Meeting")
        doc_date = document.get("date", "unknown")
        content = document.get("content", "")

        issue_lines = self._extract_section_lines(content, "Issues Addressed")
        action_lines = self._extract_section_lines(content, "Action Items")

        parts = [f"Source: {title} ({doc_date})"]
        if issue_lines:
            parts.append("Issues: " + "; ".join(issue_lines[:3]))
        if action_lines:
            parts.append("Actions: " + "; ".join(action_lines[:3]))

        description = "\n".join(parts)
        return description[:500]

