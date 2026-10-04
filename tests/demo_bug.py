"""
Demo bug file for testing local model bug solver.
"""


def calculate_discount(price: float, discount_pct: float) -> float:
    """Calculate discounted price. 20% discount on $100 should be $80."""
    return price * (1 - discount_pct / 100)
