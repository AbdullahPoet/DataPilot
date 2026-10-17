from pathlib import Path

import streamlit as st

from datapilot.persistence.session_repository import (
    get_session,
    initialize_sessions,
    list_sessions,
    set_pinned,
    touch_session,
)
from datapilot.persistence.sqlite_manager import initialize_database


def render_sidebar(database_path: Path) -> None:
    initialize_database(database_path)
    initialize_sessions(database_path)

    with st.sidebar:
        st.title("DataPilot")
        if st.button("New Analytics", width="stretch"):
            st.session_state.active_session_id = None
            st.session_state.session_config = None
            st.session_state.page = "configuration"
            st.rerun()

        sessions = list_sessions(database_path)
        pinned_sessions = [session for session in sessions if session["is_pinned"]]
        recent_sessions = [session for session in sessions if not session["is_pinned"]]

        for heading, entries in (("Pinned", pinned_sessions), ("Recent", recent_sessions)):
            if not entries:
                continue
            st.subheader(heading)
            for session in entries:
                session_id = str(session["session_id"])
                title = str(session["title"])
                session_columns = st.columns([5, 1])
                with session_columns[0]:
                    if st.button(title, key=f"open_{session_id}", width="stretch"):
                        saved_session = get_session(database_path, session_id)
                        if saved_session is None:
                            st.error("This session is no longer available.")
                            continue
                        touch_session(database_path, session_id)
                        st.session_state.active_session_id = session_id
                        st.session_state.session_config = saved_session["configuration"]
                        st.session_state.page = "chat"
                        st.rerun()
                with session_columns[1]:
                    pinned = bool(session["is_pinned"])
                    action = "Unpin" if pinned else "Pin"
                    if st.button(action, key=f"pin_{session_id}"):
                        set_pinned(database_path, session_id, not pinned)
                        st.rerun()
