from enum import Enum


# Daily Wire membership levels, plus the VODLoft choice of the highest level the account allows
class DwMembershipLevel(Enum):
    # Whatever the signed-in account's membership allows
    HIGHEST_ALLOWED = "HIGHEST_ALLOWED"

    # DailyWire
    FREE = "FREE"
    READER = "READER"
    INSIDER = "INSIDER"
    INSIDER_PLUS = "INSIDER_PLUS"
    ALL_ACCESS = "ALL_ACCESS"