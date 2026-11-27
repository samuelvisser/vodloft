from ...contract import AccountSignIn, ListOrder, SignInKind
from .email_sign_in import EMAIL_FIELDS
from .other_sites import OtherSites


class CuriosityStream(OtherSites):
    key = "curiositystream"
    name = "CuriosityStream"
    initials = "CS"
    domains = ("curiositystream.com",)
    # A series or a collection lists its videos in their order.
    list_order = ListOrder.OLDEST_FIRST
    # CuriosityStream trades the email address and password for a token, which VODLoft keeps instead of the password.
    account_sign_in = AccountSignIn(
        SignInKind.PASSWORD,
        "Sign in with your CuriosityStream account to download the videos your subscription includes. VODLoft keeps "
        "the sign-in CuriosityStream gives, not your password.",
        EMAIL_FIELDS,
    )
