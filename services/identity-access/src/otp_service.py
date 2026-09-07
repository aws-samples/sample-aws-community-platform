"""In-service OTP re-verification (US-1.32, design decision Q2).

Issue a short-lived numeric code (stored hashed), verify with expiry + attempt
cap + no user enumeration (BR-A5/A6). Delivered via SES.

The challenge also CARRIES THE COGNITO ID TOKEN minted during `login` (fix
2026-08-11). The password is verified by Cognito before OTP is even considered,
so the token exists at `issue` time and cannot be re-minted at `verify` time
(that would need the password again). Previously it was discarded and
`verify_otp` returned a `session-<userId>` placeholder, which the API Gateway
Cognito authorizer rejects — every OTP-gated login 401'd on its first API call.
The challenge record is the right place to hold it: 5-minute TTL, deleted on
first successful verify, on a table with SSE enabled.
"""
from __future__ import annotations

import secrets as _secrets

from models import epoch, new_id
from providers import hash_password, verify_password

OTP_TTL_SECONDS = 300          # 5-minute expiry (BR-A5)
OTP_MAX_ATTEMPTS = 5
OTP_CODE_DIGITS = 6


class OtpService:
    def __init__(self, repo, ses):
        self._repo = repo
        self._ses = ses

    def issue(self, user: dict, id_token: str = "") -> str:
        """`id_token` is the Cognito ID token from the password step, held for the
        life of the challenge so `verify` can return a real session token."""
        code = "".join(_secrets.choice("0123456789") for _ in range(OTP_CODE_DIGITS))
        challenge_id = new_id("otp")
        self._repo.put_otp({
            "challengeId": challenge_id,
            "userId": user["id"],
            "codeHash": hash_password(code),
            "idToken": id_token,
            "expiresAt": epoch() + OTP_TTL_SECONDS,
            "attempts": 0,
            "ttl": epoch() + OTP_TTL_SECONDS,
        })
        # Delivered to the registered (corporate) email; ties access to mailbox control.
        self._ses.send(
            user["email"],
            "Your community portal verification code",
            f"Your one-time verification code is {code}. It expires in 5 minutes.",
        )
        return challenge_id

    def verify(self, challenge_id: str, code: str) -> dict | None:
        """Return the consumed challenge (carrying `userId` and `idToken`) on
        success; None on any failure (no enumeration). Returns the whole record
        rather than a tuple so adding a field later doesn't reshape callers.

        Security (2026-08-13): the attempt counter is incremented ATOMICALLY
        BEFORE the code is checked, closing the TOCTOU race that allowed
        concurrent requests to bypass the 5-attempt limit."""
        challenge = self._repo.get_otp(challenge_id)
        if not challenge:
            return None
        # Atomic increment-first: claims an attempt slot BEFORE verifying.
        # If the limit is already reached, this fails immediately — no code
        # check happens, no matter how many concurrent requests arrive.
        if not self._repo.increment_otp_attempts(challenge_id, OTP_MAX_ATTEMPTS):
            # Limit reached — delete the challenge (it's burned).
            self._repo.delete_otp(challenge_id)
            return None
        if verify_password(code, challenge.get("codeHash", "")):
            self._repo.delete_otp(challenge_id)
            return challenge
        return None
