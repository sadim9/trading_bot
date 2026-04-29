"""
dashboard/auth.py — Authentication layer for the Streamlit dashboard.

Provides:
  - show_login_page()   — renders the login/register form
  - require_auth()      — guard; redirects to login if not authenticated
  - get_api_client()    — returns an authenticated APIClient
  - logout()            — clears session state
"""

from __future__ import annotations

import streamlit as st
from dashboard.api_client import APIClient


# ── Session State Keys ────────────────────────────────────────────────────────
_TOKEN_KEY    = "_auth_token"
_USER_KEY     = "_auth_user"
_REFRESH_KEY  = "_auth_refresh"


def is_authenticated() -> bool:
    return bool(st.session_state.get(_TOKEN_KEY))


def get_api_client() -> APIClient:
    """Return an APIClient using the current session token."""
    token = st.session_state.get(_TOKEN_KEY)
    return APIClient(token=token)


def logout():
    for key in [_TOKEN_KEY, _USER_KEY, _REFRESH_KEY]:
        st.session_state.pop(key, None)
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
                    st.session_state[_TOKEN_KEY]   = resp["access_token"]
                    st.session_state[_REFRESH_KEY] = resp["refresh_token"]
                    st.session_state[_USER_KEY]    = {
                        "user_id":  resp["user_id"],
                        "username": resp["username"],
                        "role":     resp["role"],
                    }
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
    """Call at the top of any page that requires authentication."""
    if not is_authenticated():
        show_login_page()
