from ...contract import Access, AccountSignIn, ApiField, SignInKind
from .other_sites import MEMBERS_KEY, PREMIUM_KEY, OtherSites


class Niconico(OtherSites):
    key = "niconico"
    name = "Niconico"
    initials = "NC"
    domains = ("nicovideo.jp",)
    accesses = (
        Access(MEMBERS_KEY, "Channel members only", "Only members of the channel can watch this."),
        Access(PREMIUM_KEY, "Niconico Premium", "Only Niconico Premium members can watch this."),
    )
    # Niconico's sign-in runs out, so VODLoft signs in again by itself. An account with a one-time code can't.
    account_sign_in = AccountSignIn(
        SignInKind.PASSWORD,
        "Sign in with your Niconico account to download members-only and Premium videos your account may watch. "
        "Niconico's sign-in runs out after a while, so VODLoft keeps your email address and password to sign in "
        "again by itself. An account that asks for a one-time code can't sign in here; use a cookies file instead.",
        (ApiField("email", "Email address or phone number"), ApiField("password", "Password", secret=True)),
    )
