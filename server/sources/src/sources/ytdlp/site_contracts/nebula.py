from ...contract import AccountSignIn, SignInKind
from .email_sign_in import EMAIL_FIELDS
from .other_sites import OtherSites


class Nebula(OtherSites):
    key = "nebula"
    name = "Nebula"
    initials = "NB"
    domains = ("nebula.tv", "watchnebula.com", "nebula.app")
    # Nebula trades the email address and password for a token, which VODLoft keeps instead of the password.
    account_sign_in = AccountSignIn(
        SignInKind.PASSWORD,
        "Sign in with your Nebula account to download the videos your subscription includes. VODLoft keeps the "
        "sign-in Nebula gives, not your password.",
        EMAIL_FIELDS,
    )
