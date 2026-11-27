from ...contract import AccountSignIn, ListOrder, SignInKind
from .email_sign_in import EMAIL_FIELDS
from .other_sites import OtherSites


class Dropout(OtherSites):
    key = "dropout"
    name = "Dropout"
    initials = "DO"
    domains = ("dropout.tv",)
    # A series lists its episodes in their order.
    list_order = ListOrder.OLDEST_FIRST
    # Every video on Dropout needs a subscription. Its sign-in runs out, so VODLoft signs in again by itself.
    account_sign_in = AccountSignIn(
        SignInKind.PASSWORD,
        "Sign in with your Dropout account, which needs a subscription, to download its videos. Dropout's sign-in "
        "runs out after a while, so VODLoft keeps your email address and password to sign in again by itself.",
        EMAIL_FIELDS,
    )
