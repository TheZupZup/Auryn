"""Known streamrip error patterns mapped to user-friendly messages."""


def parse_streamrip_error(output: str):
    """Return a user-friendly message if output matches a known streamrip error, else None."""
    lo = output.lower()

    if any(p in lo for p in [
        "authenticationerror", "authentication failed", "authentication error",
        "login failed", "invalid credentials", "incorrect password",
        "invalid email", "wrong password", "unauthorized",
        "could not authenticate", "not authenticated",
    ]):
        return "❌  Authentication failed — check your credentials in accounts.json."

    if any(p in lo for p in ["invalid arl", "arl expired", "arl is invalid", "bad arl"]):
        return "❌  Deezer ARL token is invalid or expired — update it in accounts.json."

    if any(p in lo for p in [
        "invalid token", "token expired", "token is invalid", "token has expired",
    ]):
        return "❌  Access token is invalid or expired — re-authenticate your account."

    if any(p in lo for p in [
        "track not found", "album not found", "resource not found",
        "resourcenotfounderror", "not available in your region", "does not exist",
    ]):
        return "❌  Content not found — the track or album may be unavailable."

    if any(p in lo for p in [
        "connectionerror", "connection refused", "network error",
        "sslerror", "ssl error", "name or service not known",
        "nodename nor servname provided", "errno 111", "errno 110",
        "timed out", "read timeout", "connection timed out",
    ]):
        return "❌  Network error — check your internet connection and try again."

    return None
