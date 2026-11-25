"""Display formatting. The backend sends ready-to-show strings, so the frontend does no maths."""


def indian_int(n: float) -> str:
    """12345678 -> '1,23,45,678' (lakh/crore grouping)."""
    neg = n < 0
    s = str(int(round(abs(n))))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        s = ",".join(groups + [tail])
    return ("-" if neg else "") + s


def rupees(n: float, decimals: int = 0) -> str:
    """7028 -> '₹7,028'; 11.7 with decimals=1 -> '₹11.7'."""
    if decimals:
        whole, frac = f"{abs(n):.{decimals}f}".split(".")
        return f"{'-' if n < 0 else ''}₹{indian_int(float(whole))}.{frac}"
    return f"{'-' if n < 0 else ''}₹{indian_int(abs(n))}"


def crore(n: float) -> str:
    """Screener reports company figures in ₹ crore."""
    return f"{rupees(n)} Cr"


def pct(n: float, decimals: int = 1, signed: bool = False) -> str:
    sign = "+" if signed and n > 0 else ""
    return f"{sign}{n:.{decimals}f}%"
