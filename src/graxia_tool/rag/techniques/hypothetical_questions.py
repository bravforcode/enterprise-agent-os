"""Enterprise Agent OS — Hypothetical Questions Technique.

Generates hypothetical questions that each document chunk could answer,
then uses those questions as additional retrieval signals for better matching.

Based on HyDe (Hypothetical Document Embedding) and HyPE (Hypothetical
Prompt Embeddings) patterns from rag-techniques.
"""
from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple

from ..chunker import Chunk


# Question templates for different content patterns
_QUESTION_TEMPLATES = {
    "definition": [
        "What is {subject}?",
        "Define {subject}.",
        "How would you explain {subject}?",
    ],
    "process": [
        "How does {subject} work?",
        "What are the steps involved in {subject}?",
        "Describe the process of {subject}.",
    ],
    "comparison": [
        "What are the differences between {subject}?",
        "How does {subject} compare to alternatives?",
        "What are the pros and cons of {subject}?",
    ],
    "factual": [
        "What are the key facts about {subject}?",
        "What is known about {subject}?",
        "What does the document say about {subject}?",
    ],
}


def _extract_subject(content: str) -> str:
    """Extract the main subject from a chunk's content.

    Uses simple heuristics: first sentence, first noun phrase, or
    the first meaningful segment.
    """
    # Try first sentence
    sentences = re.split(r"[.!?]\s+", content.strip())
    first_sentence = sentences[0] if sentences else content[:100]

    # Remove leading articles and common starters
    cleaned = re.sub(
        r"^(The|A|An|This|These|Those|In|On|At|For|To|By)\s+",
        "",
        first_sentence,
        flags=re.IGNORECASE,
    )

    # Take first clause (up to first comma or 50 chars)
    clause_match = re.match(r"([^,]{5,50})", cleaned)
    if clause_match:
        return clause_match.group(1).strip()

    return cleaned[:80].strip()


def _classify_content(content: str) -> str:
    """Classify the content type for question template selection."""
    lower = content.lower()

    if any(w in lower for w in ["is defined as", "refers to", "means that", "is a type of"]):
        return "definition"
    elif any(w in lower for w in ["process", "steps", "method", "approach", "workflow", "pipeline"]):
        return "process"
    elif any(w in lower for w in ["compare", "difference", "versus", "vs", "advantage", "disadvantage"]):
        return "comparison"
    else:
        return "factual"


def generate_questions(
    chunk: Chunk,
    num_questions: int = 3,
) -> List[str]:
    """Generate hypothetical questions that the chunk could answer.

    Args:
        chunk: The document chunk to generate questions for.
        num_questions: Maximum number of questions to generate.

    Returns:
        List of generated question strings.
    """
    content_type = _classify_content(chunk.content)
    subject = _extract_subject(chunk.content)

    templates = _QUESTION_TEMPLATES.get(content_type, _QUESTION_TEMPLATES["factual"])
    questions = []

    for template in templates[:num_questions]:
        try:
            question = template.format(subject=subject)
            questions.append(question)
        except (KeyError, IndexError):
            # Fallback: generic question
            questions.append(f"What does this section say about {subject}?")

    # Add a content-aware question based on first few words
    words = chunk.content.split()[:15]
    if len(words) > 3:
        keyword_phrase = " ".join(words[:5])
        questions.append(f"What information is provided about '{keyword_phrase}'?")

    return questions[:num_questions]


def generate_hypothetical_query(
    query: str,
    llm_func=None,
) -> str:
    """Generate a hypothetical document/query expansion using LLM.

    Implements the HyDE pattern: transforms a short query into a fuller
    hypothetical document that would contain the answer.

    Args:
        query: Original search query.
        llm_func: Optional async LLM function for generation.

    Returns:
        Expanded query string for better retrieval.
    """
    if not llm_func:
        # Fallback: simple query expansion without LLM
        return _simple_query_expansion(query)

    # Use LLM to generate hypothetical document
    prompt = (
        f"Write a short paragraph (2-3 sentences) that would be the perfect "
        f"answer to this question. Focus on factual, specific information.\n\n"
        f"Question: {query}\n\n"
        f"Hypothetical answer paragraph:"
    )
    # This is sync; caller should use llm_rerank for async
    return prompt


def _simple_query_expansion(query: str) -> str:
    """Expand query without LLM by adding synonyms and related terms."""
    # Simple expansion: add key terms and variations
    words = query.split()
    expanded_terms = list(words)

    # Add common related terms for technical queries
    tech_synonyms = {
        "how": ["method", "process", "approach"],
        "what": ["definition", "description", "explanation"],
        "why": ["reason", "cause", "purpose"],
        "when": ["time", "date", "when"],
        "where": ["location", "place", "where"],
    }

    for word in words:
        lower = word.lower()
        if lower in tech_synonyms:
            expanded_terms.extend(tech_synonyms[lower][:2])

    return " ".join(expanded_terms)


def index_with_questions(
    chunks: List[Chunk],
    num_questions: int = 2,
) -> Dict[str, List[str]]:
    """Generate questions for all chunks and return a question index.

    Args:
        chunks: List of chunks to process.
        num_questions: Number of questions per chunk.

    Returns:
        Dict mapping chunk_id to list of generated questions.
    """
    question_index: Dict[str, List[str]] = {}

    for chunk in chunks:
        questions = generate_questions(chunk, num_questions=num_questions)
        question_index[chunk.id] = questions

    return question_index


def retrieve_with_questions(
    query: str,
    chunks: List[Chunk],
    question_index: Dict[str, List[str]],
    top_k: int = 5,
) -> List[Tuple[Chunk, float]]:
    """Retrieve chunks using both content and generated questions as signals.

    Combines direct content matching with question-answer matching
    for improved retrieval.

    Args:
        query: Search query.
        chunks: List of indexed chunks.
        question_index: Question index from index_with_questions.
        top_k: Number of results to return.

    Returns:
        List of (chunk, score) tuples sorted by relevance.
    """
    from .hybrid_search import TFIDFIndex, _tokenize

    # Score 1: Direct content match
    content_tfidf = TFIDFIndex([c.content for c in chunks])
    content_scores = content_tfidf.search(query, top_k=len(chunks))
    content_score_map = {idx: score for idx, score in content_scores}

    # Score 2: Question match
    all_questions = []
    chunk_for_question = []
    for chunk in chunks:
        questions = question_index.get(chunk.id, [])
        for q in questions:
            all_questions.append(q)
            chunk_for_question.append(chunk)

    question_tfidf = TFIDFIndex(all_questions) if all_questions else None
    question_scores = question_tfidf.search(query, top_k=len(all_questions)) if question_tfidf else []

    # Aggregate question scores per chunk
    q_score_map: Dict[int, float] = {}
    for q_idx, q_score in question_scores:
        chunk_idx = chunk_for_question[q_idx].index if q_idx < len(chunk_for_question) else 0
        q_score_map[chunk_idx] = q_score_map.get(chunk_idx, 0) + q_score

    # Combine scores
    results = []
    for i, chunk in enumerate(chunks):
        c_score = content_score_map.get(i, 0.0)
        q_score = q_score_map.get(i, 0.0)
        # Weight: 60% content, 40% question match
        combined = 0.6 * c_score + 0.4 * q_score
        if combined > 0:
            results.append((chunk, combined))

    results.sort(key=lambda x: -x[1])
    return results[:top_k]
