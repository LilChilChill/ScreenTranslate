import anthropic


def translate(text: str, src_lang: str, tgt_lang: str, api_key: str) -> str:
    """Dịch văn bản bằng Claude API. src_lang/tgt_lang là tên đầy đủ (vd: 'English')."""
    if not text.strip():
        return ""
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1024,
        system=(
            "You are a professional translator. "
            "Translate the given text accurately and naturally. "
            "Return only the translated text, nothing else."
        ),
        messages=[
            {
                "role": "user",
                "content": f"Translate from {src_lang} to {tgt_lang}:\n\n{text}",
            }
        ],
    )
    return msg.content[0].text
