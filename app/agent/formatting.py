"""Presentation only; query values remain bytes (decimal SI units)."""


def format_size(value):
    if value is None:
        return "확인 불가"
    amount = float(value)
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    index = 0
    while abs(amount) >= 1000 and index < len(units) - 1:
        amount /= 1000
        index += 1
    text = f"{amount:,.2f}".rstrip("0").rstrip(".")
    return f"{text} {units[index]}"
