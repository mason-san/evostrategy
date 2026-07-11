"""
Minimal local auth for the verification dashboard.

No internet dependency, matches the project's local-only deployment
requirement. Passwords are bcrypt-hashed, never stored in plaintext.
Swap this for streamlit-authenticator later if you want a fancier
login widget — the session_state contract below stays the same either
way, so nothing downstream needs to change.

To add a new user: run `python auth.py` and follow the prompt, it
will print a hash you can paste into USERS below.
"""

import bcrypt
import streamlit as st

# username -> {password_hash, role}
# role is one of: "reviewer", "admin"
USERS = {
    "ayushi": {
        "password_hash": bcrypt.hashpw(b"changeme123", bcrypt.gensalt()).decode(),
        "role": "admin",
    },
    "reviewer1": {
        "password_hash": bcrypt.hashpw(b"changeme123", bcrypt.gensalt()).decode(),
        "role": "reviewer",
    },
}


def check_login(username: str, password: str):
    user = USERS.get(username)
    if not user:
        return None
    if bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return {"username": username, "role": user["role"]}
    return None


def login_screen():
    """Renders the login form. Returns True once logged in."""
    if "user" in st.session_state:
        return True

    st.title("EvoStrategy — Verification Dashboard")
    st.subheader("Sign in")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in")

    if submitted:
        user = check_login(username, password)
        if user:
            import datetime

            st.session_state["user"] = {
                **user,
                "login_time": datetime.datetime.now().isoformat(timespec="seconds"),
            }
            st.rerun()
        else:
            st.error("Incorrect username or password.")

    return False


def logout_button():
    if st.sidebar.button("Log out"):
        del st.session_state["user"]
        st.rerun()


if __name__ == "__main__":
    pw = input("Password to hash: ")
    print(bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode())
