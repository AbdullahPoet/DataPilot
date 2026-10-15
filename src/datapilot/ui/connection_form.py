from pathlib import Path

import streamlit as st
from sqlalchemy import create_engine
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from datapilot.connections.connection_manager import ConnectionInfo, test_connection
from datapilot.knowledge.schema_cache import load_schema_knowledge


def render_connection_form(knowledge_directory: Path) -> ConnectionInfo | None:
    st.subheader("SQL Database Connection")
    with st.form("sql_connection_form"):
        dialect = st.selectbox("Database type", ("SQLite", "PostgreSQL", "MySQL"))
        if dialect == "SQLite":
            file_path = st.text_input("Existing database file path")
            host = ""
            port = 0
            database = ""
            username = ""
            password = ""
        else:
            file_path = ""
            host = st.text_input("Host", value="localhost")
            port = st.number_input(
                "Port", min_value=1, max_value=65535, value=5432 if dialect == "PostgreSQL" else 3306
            )
            database = st.text_input("Database name")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
        connect = st.form_submit_button("Connect and load schema")
        refresh = st.form_submit_button("Refresh Database Understanding")

    if not (connect or refresh):
        return None

    if dialect == "SQLite":
        if not file_path.strip():
            st.error("Select an existing SQLite database file.")
            return None
        url = URL.create("sqlite", database=str(Path(file_path).expanduser()))
    else:
        if not host.strip() or not database.strip() or not username.strip():
            st.error("Host, database name, and username are required.")
            return None
        url = URL.create(
            "postgresql+psycopg" if dialect == "PostgreSQL" else "mysql+pymysql",
            username=username,
            password=password,
            host=host,
            port=int(port),
            database=database,
        )

    connection_url = url.render_as_string(hide_password=False)
    try:
        info = test_connection(connection_url)
        engine = create_engine(url, pool_pre_ping=True)
        try:
            knowledge = load_schema_knowledge(engine, knowledge_directory, refresh=refresh)
        finally:
            engine.dispose()
    except (ValueError, FileNotFoundError, ConnectionError, SQLAlchemyError, ImportError, OSError):
        st.error("Unable to connect or inspect the selected database. Check the connection details and permissions.")
        return None

    st.success("Database connection verified.")
    st.text_area("Verified database understanding", value=knowledge, height=260, disabled=True)
    return info
