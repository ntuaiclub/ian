def split_message_chunks(
    text: str,
    *,
    max_length: int = 2000,
    max_chunks: int = 5,
) -> list[str]:
    """Split text into platform-sized chunks, preserving paragraphs when possible."""
    if max_length <= 0:
        raise ValueError("max_length must be positive")
    if max_chunks <= 0:
        return []

    chunks: list[str] = []
    current_chunk = ""

    for paragraph in text.split("\n\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue

        if len(paragraph) > max_length:
            if current_chunk:
                chunks.append(current_chunk.strip())
                current_chunk = ""
            chunks.extend(_split_long_paragraph(paragraph, max_length))
        elif not current_chunk:
            current_chunk = paragraph
        elif len(current_chunk) + len(paragraph) + 2 <= max_length:
            current_chunk += "\n\n" + paragraph
        else:
            chunks.append(current_chunk.strip())
            current_chunk = paragraph

        if len(chunks) >= max_chunks:
            return chunks[:max_chunks]

    if current_chunk:
        chunks.append(current_chunk.strip())

    return [chunk for chunk in chunks if chunk.strip()][:max_chunks]


def _split_long_paragraph(paragraph: str, max_length: int) -> list[str]:
    return [
        paragraph[start : start + max_length]
        for start in range(0, len(paragraph), max_length)
    ]
