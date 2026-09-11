from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from allauth.socialaccount.models import SocialLogin
from allauth.core.exceptions import ImmediateHttpResponse

from .models import SchoolProfile


NOT_PROVISIONED = "You are not authorised to use this service."
NO_SCHOOL = "Your account is not configured with a school yet."
SIGNUP_CLOSED = "Accounts are created by the Trust. Sign in with your Microsoft account."


def provisioning_problem(user) -> str | None:
    """Return why this user may not sign in, or None if they may.

    This is the one authorisation rule for every door into OSED. Microsoft
    (or a password) authenticates the person; we authorise by pre-provisioning:
    an active User with a SchoolProfile. Superusers see every school and need
    no profile. Keep this the only place the rule is written — both adapters
    below call it, so the two login paths cannot drift apart.
    """
    if user is None or not user.is_active:
        return NOT_PROVISIONED
    if user.is_superuser:
        return None
    if not SchoolProfile.objects.filter(user=user).exists():
        return NO_SCHOOL
    return None


def _deny(request: HttpRequest, message: str) -> HttpResponse:
    messages.error(request, message)
    return redirect("account_login")


class OsedAccountAdapter(DefaultAccountAdapter):
    """Guards the two entrances the social adapter never sees.

    - Self-registration: allauth has no ``ACCOUNT_ALLOW_SIGNUPS`` setting; the
      only switch is this hook. /accounts/signup/ is sent back to the login
      page rather than rendering allauth's unstyled "closed" page.
    - Password login: ``pre_login`` runs inside ``perform_login`` for every
      login, password or social, so the provisioning rule holds on both doors.
      The login page offers the password form for staff who cannot use
      Microsoft; a password gets no one past the rule that SSO would not.
    """

    def is_open_for_signup(self, request: HttpRequest) -> bool:
        raise ImmediateHttpResponse(_deny(request, SIGNUP_CLOSED))

    def pre_login(self, request: HttpRequest, user, **kwargs):
        response = super().pre_login(request, user, **kwargs)
        if response is not None:
            return response
        problem = provisioning_problem(user)
        if problem:
            return _deny(request, problem)
        return None


class RestrictMicrosoftLoginAdapter(DefaultSocialAccountAdapter):
    """Only allow Microsoft SSO logins for pre-provisioned emails.

    Security model:
    - Microsoft (Entra) authenticates the person.
    - We authorize by checking the email exists as a Django User and has a SchoolProfile.
    """

    def pre_social_login(self, request: HttpRequest, sociallogin: SocialLogin):
        email = (sociallogin.user.email or "").strip().lower()
        if not email:
            raise ImmediateHttpResponse(
                _deny(request, "Your Microsoft account did not provide an email address.")
            )

        # Match an existing, pre-provisioned user.
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        problem = provisioning_problem(user)
        if problem:
            raise ImmediateHttpResponse(_deny(request, problem))

        # Link the social account to the existing user.
        sociallogin.connect(request, user)
