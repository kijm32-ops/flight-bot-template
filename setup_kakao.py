"""One-time local OAuth setup for PTIS Kakao "send to me" delivery."""

import argparse
import os
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests

from kakao_auth import KakaoAuthError, generate_encryption_key, store_refresh_token


AUTHORIZATION_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
REQUIRED_SCOPE = "talk_message"


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise KakaoAuthError(f"{name} is required.")
    return value


def _local_callback(redirect_uri: str):
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise KakaoAuthError("KAKAO_REDIRECT_URI must be an http localhost callback URL.")
    if not parsed.port or not parsed.path:
        raise KakaoAuthError("KAKAO_REDIRECT_URI must include a port and path.")
    return parsed


def _authorization_url(rest_api_key: str, redirect_uri: str, state: str) -> str:
    query = urlencode({
        "response_type": "code",
        "client_id": rest_api_key,
        "redirect_uri": redirect_uri,
        "scope": REQUIRED_SCOPE,
        "state": state,
    })
    return f"{AUTHORIZATION_URL}?{query}"


def _wait_for_code(callback, expected_state: str) -> str:
    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            values = parse_qs(parsed.query)
            if parsed.path != callback.path:
                self.send_error(404)
                return
            if values.get("state", [""])[0] != expected_state:
                self.send_error(400, "OAuth state mismatch")
                self.server.oauth_error = "OAuth state mismatch"
                return
            self.server.oauth_code = values.get("code", [""])[0]
            self.server.oauth_error = values.get("error", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"PTIS Kakao authorization received. You can close this page.")

        def log_message(self, format, *args):
            return

    server = HTTPServer((callback.hostname, callback.port), CallbackHandler)
    server.timeout = 300
    server.oauth_code = ""
    server.oauth_error = ""
    try:
        while not server.oauth_code and not server.oauth_error:
            server.handle_request()
            if not server.oauth_code and not server.oauth_error:
                raise KakaoAuthError("Timed out waiting for the Kakao OAuth callback.")
    finally:
        server.server_close()
    if server.oauth_error:
        raise KakaoAuthError(f"Kakao authorization failed: {server.oauth_error}")
    return server.oauth_code


def _safe_token_error(response) -> KakaoAuthError:
    parts = []
    try:
        payload = response.json()
    except (ValueError, requests.JSONDecodeError):
        payload = {}
    if isinstance(payload, dict):
        for key in ("error", "error_description", "error_code"):
            value = payload.get(key)
            if isinstance(value, (str, int, float)) and str(value).strip():
                parts.append(f"{key}={value}")
    detail = f" ({', '.join(parts)})" if parts else ""
    return KakaoAuthError(
        f"Kakao token endpoint returned HTTP {response.status_code}{detail}."
    )


def _exchange_code(code: str, rest_api_key: str, redirect_uri: str, client_secret: str):
    data = {
        "grant_type": "authorization_code",
        "client_id": rest_api_key,
        "redirect_uri": redirect_uri,
        "code": code,
    }
    if client_secret:
        data["client_secret"] = client_secret
    response = requests.post(TOKEN_URL, data=data, timeout=15)
    if not response.ok:
        raise _safe_token_error(response)
    payload = response.json()
    refresh_token = payload.get("refresh_token")
    scopes = set(str(payload.get("scope", "")).split())
    if not isinstance(refresh_token, str) or not refresh_token:
        raise KakaoAuthError("Kakao token response did not include a refresh token.")
    if REQUIRED_SCOPE not in scopes:
        raise KakaoAuthError("Kakao token is missing the required talk_message scope.")
    return refresh_token


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-encryption-key", action="store_true")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    if args.print_encryption_key:
        print(generate_encryption_key())
        return 0

    try:
        rest_api_key = _required_env("KAKAO_REST_API_KEY")
        encryption_key = _required_env("KAKAO_TOKEN_ENCRYPTION_KEY")
        redirect_uri = _required_env("KAKAO_REDIRECT_URI")
        callback = _local_callback(redirect_uri)
        state = secrets.token_urlsafe(32)
        url = _authorization_url(rest_api_key, redirect_uri, state)
        print("Open this Kakao authorization URL if the browser does not open:")
        print(url)
        if not args.no_browser:
            webbrowser.open(url)
        code = _wait_for_code(callback, state)
        refresh_token = _exchange_code(
            code, rest_api_key, redirect_uri, os.environ.get("KAKAO_CLIENT_SECRET", "")
        )
        store_refresh_token(refresh_token, encryption_key)
        print("Kakao OAuth setup succeeded. Commit data/kakao_auth.json to your repository.")
        return 0
    except (KakaoAuthError, requests.RequestException) as exc:
        print(f"Kakao OAuth setup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
