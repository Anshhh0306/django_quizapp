def to_int(value, max_value=10**9):
    """A whole number from user input, or None.

    'x'.isdigit() is True for characters like '²' that int() cannot read, and a 30-digit number overflows the
    database. This accepts only plain ASCII digits and a sane size."""
    text = str(value).strip()
    if not (text.isascii() and text.isdigit()) or len(text) > 10:
        return None
    number = int(text)
    return number if number <= max_value else None
