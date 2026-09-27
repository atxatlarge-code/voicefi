"""
Unit test for demo bug.
"""

from tests.demo_bug import calculate_discount


def test_calculate_discount():
    # 20% discount on $100 should be $80.0
    assert calculate_discount(100.0, 0.20) == 80.0
