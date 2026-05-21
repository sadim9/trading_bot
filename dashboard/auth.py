"""
dashboard/auth.py — Authentication layer for the Streamlit dashboard.

Provides:
  - show_login_page()   — renders the login/register form
  - require_auth()      — guard; redirects to login if not authenticated
  - get_api_client()    — returns an authenticated APIClient
  - logout()            — clears session state

Token persistence: the access token is saved to user_settings.json under
_auth_token_saved / _auth_token_expiry so browser refreshes do not log the
user out. On each page load require_auth() restores the token from disk
if the saved copy is still within its TTL.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import streamlit as st
from dashboard.api_client import APIClient


# ── Session State Keys ────────────────────────────────────────────────────────
_TOKEN_KEY    = "_auth_token"
_USER_KEY     = "_auth_user"
_REFRESH_KEY  = "_auth_refresh"

# ── Token persistence ──────────────────────────────────────────────────────────
_SETTINGS_DIR  = Path(os.getenv("SETTINGS_DIR", "/app/logs"))
_TOKEN_FILE    = _SETTINGS_DIR / "session_token.json"
# How long (seconds) to keep the saved token valid after it was last written.
# JWT tokens usually expire in 30 min–8 h; we treat a saved token as valid
# for 8 hours so a normal trading session doesn't trigger a re-login.
_TOKEN_TTL     = 8 * 3600


def _save_token(token: str, refresh: str, user: dict):
    """Persist the current session token to disk so browser refreshes survive."""
    try:
        for dirpath in [_SETTINGS_DIR, Path(".cache")]:
            try:
                dirpath.mkdir(parents=True, exist_ok=True)
                path = dirpath / "session_token.json"
                tmp  = path.with_suffix(".tmp")
                tmp.write_text(json.dumps({
                    "token":   token,
                    "refresh": refresh,
                    "user":    user,
                    "saved_at": time.time(),
                }, indent=2), encoding="utf-8")
                tmp.replace(path)
                return
            except Exception:
                continue
    except Exception:
        pass


def _load_token() -> dict | None:
    """
    Load a previously saved session token if it is still within TTL.
    Returns dict with keys token/refresh/user, or None.
    """
    for path in [_SETTINGS_DIR / "session_token.json",
                 Path(".cache/session_token.json")]:
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                saved_at = float(data.get("saved_at", 0))
                if time.time() - saved_at < _TOKEN_TTL:
                    return data
        except Exception:
            pass
    return None


def _clear_saved_token():
    """Delete the persisted token file (called on explicit logout)."""
    for path in [_SETTINGS_DIR / "session_token.json",
                 Path(".cache/session_token.json")]:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass


def is_authenticated() -> bool:
    return bool(st.session_state.get(_TOKEN_KEY))


def get_api_client() -> APIClient:
    """Return an APIClient using the current session token."""
    token = st.session_state.get(_TOKEN_KEY)
    return APIClient(token=token)


def logout():
    for key in [_TOKEN_KEY, _USER_KEY, _REFRESH_KEY]:
        st.session_state.pop(key, None)
    _clear_saved_token()
    st.rerun()


def show_login_page():
    """Render a full-page login / register form. Returns only after login."""

    st.markdown("""
    <style>
    /* ── Mobile-first login form ── */
    .auth-container {
        max-width: 420px;
        margin: 40px auto 0;
        background: #0C1322;
        border: 1px solid #1A2540;
        border-radius: 8px;
        padding: 40px 36px;
        box-sizing: border-box;
    }
    .auth-title {
        font-family: 'IBM Plex Mono', monospace;
        font-size: 22px;
        font-weight: 600;
        color: #DCE4F5;
        letter-spacing: 0.08em;
        margin-bottom: 6px;
    }
    .auth-subtitle {
        color: #7A8BA8;
        font-size: 13px;
        margin-bottom: 28px;
    }
    /* Prevent horizontal scroll on small screens */
    @media (max-width: 480px) {
        .auth-container {
            margin: 16px auto 0;
            padding: 24px 18px;
            border-radius: 6px;
            /* Allow it to fill most of the narrow viewport */
            max-width: calc(100vw - 32px);
        }
        .auth-title {
            font-size: 18px;
        }
    }
    /* Ensure Streamlit's own form inputs fill the card width on mobile */
    @media (max-width: 480px) {
        .stTextInput > div > div > input {
            font-size: 16px !important; /* prevents iOS Safari auto-zoom on focus */
        }
        .stFormSubmitButton button {
            width: 100% !important;
        }
    }
    </style>
    """, unsafe_allow_html=True)

    st.markdown('<div class="auth-container">', unsafe_allow_html=True)
    st.markdown('<div class="auth-title">▲ APEX TERMINAL</div>', unsafe_allow_html=True)
    st.markdown('<div class="auth-subtitle">Secure Trading Interface</div>', unsafe_allow_html=True)

    tab_login, tab_register = st.tabs(["Sign In", "Register"])

    # ── LOGIN ──────────────────────────────────────────────────────────────────
    with tab_login:
        with st.form("login_form", clear_on_submit=False):
            username = st.text_input("Username", placeholder="your_username")
            password = st.text_input("Password", type="password", placeholder="••••••••")
            submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

        if submitted:
            if not username or not password:
                st.error("Please enter your username and password.")
            else:
                client = APIClient()
                try:
                    resp = client.login(username, password)
                    _user_dict = {
                        "user_id":  resp["user_id"],
                        "username": resp["username"],
                        "role":     resp["role"],
                    }
                    st.session_state[_TOKEN_KEY]   = resp["access_token"]
                    st.session_state[_REFRESH_KEY] = resp["refresh_token"]
                    st.session_state[_USER_KEY]    = _user_dict
                    # Persist token so browser refreshes don't log the user out
                    _save_token(resp["access_token"], resp.get("refresh_token", ""), _user_dict)
                    st.rerun()
                except RuntimeError as e:
                    st.error(str(e))

    # ── REGISTER ───────────────────────────────────────────────────────────────
    with tab_register:
        with st.form("register_form", clear_on_submit=True):
            reg_email    = st.text_input("Email", placeholder="you@example.com")
            reg_username = st.text_input("Username", placeholder="your_username", key="reg_user")
            reg_password = st.text_input("Password", type="password", key="reg_pass",
                                          help="Min 8 chars, must include uppercase, lowercase, digit, and special character.")
            reg_confirm  = st.text_input("Confirm Password", type="password", key="reg_confirm")
            submitted_reg = st.form_submit_button("Create Account", use_container_width=True)

        if submitted_reg:
            if reg_password != reg_confirm:
                st.error("Passwords do not match.")
            else:
                client = APIClient()
                try:
                    client.register(reg_email, reg_username, reg_password)
                    st.success("Account created! Please sign in.")
                except RuntimeError as e:
                    st.error(str(e))

    st.markdown('</div>', unsafe_allow_html=True)

    # Block the rest of the page from rendering
    st.stop()


def require_auth():
    """
    Call at the top of any page that requires authentication.

    On browser refresh Streamlit loses session state. This function first
    tries to restore the saved token from disk before falling back to the
    login form, so users don't get logged out by a normal page refresh.
    """
    if not is_authenticated():
        # Try to restore from disk before showing the login form
        saved = _load_token()
        if saved and saved.get("token"):
            st.session_state[_TOKEN_KEY]   = saved["token"]
            st.session_state[_REFRESH_KEY] = saved.get("refresh", "")
            st.session_state[_USER_KEY]    = saved.get("user", {})
            # Restored — no need to show login page
            return
        show_login_page()
