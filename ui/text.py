"""Markdown escaping for answer text that contains real dollar figures.

Streamlit reads `$...$` as LaTeX math, so an answer listing "$107.7B ... $9.2B"
renders as one garbled formula instead of two figures -- silently turning a
correctly grounded number into something the reader cannot check. Every answer
this app renders is full of USD amounts, so escaping is the default here rather
than a special case.
"""


def md_safe(text: str) -> str:
    return text.replace("$", "\\$")
