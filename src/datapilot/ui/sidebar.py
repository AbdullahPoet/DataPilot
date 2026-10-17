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
        st.html(
            """
            <div aria-label="DataPilot" style="display:flex;align-items:center;
                gap:10px;margin:8px 0 20px;background:transparent;">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"
                    width="36" height="36" aria-hidden="true" style="flex-shrink:0;">
                    <defs>
                        <linearGradient id="datapilot-blue" x2="0.7" y2="1">
                            <stop stop-color="#065cff"/>
                            <stop offset="1" stop-color="#00216e"/>
                        </linearGradient>
                        <mask id="datapilot-plane">
                            <rect width="64" height="64" fill="white"/>
                            <path d="M0 34 43 17Q49 15 47 22L34 64H24L35 30
                                18 38 8 34 0 43Z" fill="black"/>
                        </mask>
                    </defs>
                    <path d="M5 4H30C69 4 69 60 30 60H4V49L17 36 5 32Z"
                        fill="url(#datapilot-blue)" mask="url(#datapilot-plane)"/>
                </svg>
                <span style="font-size:28px;font-weight:700;letter-spacing:-1px;
                    line-height:1.2;white-space:nowrap;">Data<span
                    style="color:#065cff;">Pilot</span></span>
            </div>
            """
        )
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
