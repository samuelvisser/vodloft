"""What the Sites that sign in with an email address and password ask for."""
from ...contract import ApiField

EMAIL_FIELDS = (ApiField("email", "Email address"), ApiField("password", "Password", secret=True))
