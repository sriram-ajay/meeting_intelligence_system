"""
Streamlit UI for Meeting Intelligence System v2/v3.

Provides transcript upload (async), meeting browsing, grounded Q&A
with citations, persistent chat sessions, token-usage display,
LangGraph pipeline visualization, user memory profiles, and
RAG quality monitoring against the v2/v3 FastAPI backend.
"""

import streamlit as st
import httpx
import json
import os
import time
import uuid
from typing import Optional, Dict, Any, List

from shared_utils.config_loader import get_settings
from shared_utils.logging_utils import ContextualLogger
from shared_utils.constants import LogScope, APIEndpoints, Defaults
from shared_utils.error_handler import handle_error
from shared_utils.validation import InputValidator


# ---------------------------------------------------------------------------
# Configuration & logging
# ---------------------------------------------------------------------------

settings = get_settings()
logger = ContextualLogger(scope=LogScope.UI)

API_BASE = settings.get_api_base_url()

INDEX_COUNT_FILE = "data/index_count.json"


# ---------------------------------------------------------------------------
# Helpers — index counter (local bookkeeping only)
# ---------------------------------------------------------------------------

def get_index_count() -> int:
    """Get the current count of indexed documents."""
    try:
        if os.path.exists(INDEX_COUNT_FILE):
            with open(INDEX_COUNT_FILE, "r") as f:
                return json.load(f).get("count", 0)
    except Exception:
        pass
    return 0


def increment_index_count() -> int:
    """Increment and return the index count."""
    try:
        os.makedirs(os.path.dirname(INDEX_COUNT_FILE), exist_ok=True)
        count = get_index_count() + 1
        with open(INDEX_COUNT_FILE, "w") as f:
            json.dump({"count": count}, f)
        return count
    except Exception as e:
        logger.error("index_count_update_failed", error=str(e))
        return get_index_count()


def reset_database() -> bool:
    """Reset local index counter.

    NOTE: V1 LanceDB + metrics storage has been removed.
    A full reset in v2 would clear DynamoDB + S3 via the API.
    """
    try:
        if os.path.exists(INDEX_COUNT_FILE):
            os.makedirs(os.path.dirname(INDEX_COUNT_FILE), exist_ok=True)
            with open(INDEX_COUNT_FILE, "w") as f:
                json.dump({"count": 0}, f)
            logger.info("index_counter_reset")
        return True
    except Exception as e:
        logger.error("database_reset_failed", error=str(e))
        return False


def nuclear_reset() -> bool:
    """Comprehensive reset of local application state."""
    try:
        os.makedirs(os.path.dirname(INDEX_COUNT_FILE), exist_ok=True)
        with open(INDEX_COUNT_FILE, "w") as f:
            json.dump({"count": 0}, f)
        st.cache_data.clear()
        st.cache_resource.clear()
        logger.info("nuclear_reset_complete")
        return True
    except Exception as e:
        logger.error("nuclear_reset_failed", error=str(e))
        return False


# ---------------------------------------------------------------------------
# Page setup & auth
# ---------------------------------------------------------------------------

st.set_page_config(page_title=settings.app_name, layout="wide", page_icon="🎙️")

# ---------------------------------------------------------------------------
# Custom theme — calm palette with rounded modern styling
# ---------------------------------------------------------------------------

_CUSTOM_CSS = """
<style>
/* ── Colour palette (CSS variables) ────────────────────────────────── */
:root {
    --bg-primary:    #f8fafb;
    --bg-secondary:  #eef3f7;
    --bg-card:       #ffffff;
    --accent:        #4a90d9;
    --accent-hover:  #3a7bc8;
    --accent-light:  #e8f0fe;
    --text-primary:  #2c3e50;
    --text-secondary:#6b7c93;
    --text-muted:    #95a5b8;
    --border:        #dce3eb;
    --border-light:  #edf1f5;
    --success:       #48bb78;
    --success-bg:    #f0faf4;
    --warning:       #ed8936;
    --warning-bg:    #fefcf3;
    --error:         #e53e3e;
    --error-bg:      #fef2f2;
    --info-bg:       #ebf5ff;
    --shadow-sm:     0 1px 3px rgba(0,0,0,0.06);
    --shadow-md:     0 4px 12px rgba(0,0,0,0.08);
    --radius:        12px;
    --radius-sm:     8px;
    --radius-xs:     6px;
}

/* ── Global body ───────────────────────────────────────────────────── */
.stApp {
    background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%);
    color: var(--text-primary);
}

/* ── Sidebar ───────────────────────────────────────────────────────── */
section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #2c3e50 0%, #34495e 100%) !important;
    border-right: none !important;
    box-shadow: 2px 0 20px rgba(0,0,0,0.1);
}
section[data-testid="stSidebar"] * {
    color: #ecf0f1 !important;
}
section[data-testid="stSidebar"] .stMarkdown h1,
section[data-testid="stSidebar"] .stMarkdown h2,
section[data-testid="stSidebar"] .stMarkdown h3 {
    color: #ffffff !important;
    font-weight: 600;
    letter-spacing: -0.02em;
}
section[data-testid="stSidebar"] hr {
    border-color: rgba(255,255,255,0.12) !important;
    margin: 1rem 0;
}
section[data-testid="stSidebar"] .stSelectbox label,
section[data-testid="stSidebar"] .stTextInput label,
section[data-testid="stSidebar"] .stFileUploader label,
section[data-testid="stSidebar"] .stRadio label {
    color: #bdc3c7 !important;
    font-size: 0.85rem;
}
section[data-testid="stSidebar"] .stMetric {
    background: rgba(255,255,255,0.06);
    border-radius: var(--radius-sm);
    padding: 0.6rem 0.8rem;
}

/* ── Sidebar buttons ───────────────────────────────────────────────── */
section[data-testid="stSidebar"] .stButton > button {
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent-hover) 100%) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: var(--radius-sm) !important;
    padding: 0.55rem 1.2rem !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
    box-shadow: var(--shadow-sm) !important;
}
section[data-testid="stSidebar"] .stButton > button:hover {
    transform: translateY(-1px) !important;
    box-shadow: var(--shadow-md) !important;
    filter: brightness(1.08) !important;
}

/* ── Main-area buttons ─────────────────────────────────────────────── */
.stButton > button {
    border-radius: var(--radius-sm) !important;
    border: 1px solid var(--border) !important;
    padding: 0.5rem 1.2rem !important;
    font-weight: 500 !important;
    transition: all 0.2s ease !important;
    background: var(--bg-card) !important;
    color: var(--text-primary) !important;
}
.stButton > button:hover {
    border-color: var(--accent) !important;
    color: var(--accent) !important;
    box-shadow: var(--shadow-sm) !important;
    transform: translateY(-1px) !important;
}

/* ── Tabs ──────────────────────────────────────────────────────────── */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background: var(--bg-card);
    border-radius: var(--radius);
    padding: 4px;
    box-shadow: var(--shadow-sm);
    border: 1px solid var(--border-light);
}
.stTabs [data-baseweb="tab"] {
    border-radius: var(--radius-sm) !important;
    padding: 0.6rem 1.4rem !important;
    font-weight: 500 !important;
    color: var(--text-secondary) !important;
    transition: all 0.2s ease !important;
    border: none !important;
}
.stTabs [data-baseweb="tab"]:hover {
    background: var(--accent-light) !important;
    color: var(--accent) !important;
}
.stTabs [aria-selected="true"] {
    background: linear-gradient(135deg, var(--accent) 0%, var(--accent-hover) 100%) !important;
    color: #ffffff !important;
    box-shadow: var(--shadow-sm) !important;
}
.stTabs [data-baseweb="tab-highlight"],
.stTabs [data-baseweb="tab-border"] {
    display: none !important;
}

/* ── Cards / containers ────────────────────────────────────────────── */
[data-testid="stVerticalBlockBorderWrapper"] {
    border-radius: var(--radius) !important;
    border: 1px solid var(--border-light) !important;
    box-shadow: var(--shadow-sm) !important;
    background: var(--bg-card) !important;
    overflow: hidden;
}

/* ── Expanders ─────────────────────────────────────────────────────── */
.streamlit-expanderHeader {
    border-radius: var(--radius-sm) !important;
    font-weight: 500 !important;
    color: var(--text-secondary) !important;
    transition: color 0.2s ease !important;
    font-size: 0.9rem !important;
}
.streamlit-expanderHeader:hover {
    color: var(--accent) !important;
}

/* ── Chat messages ─────────────────────────────────────────────────── */
[data-testid="stChatMessage"] {
    border-radius: var(--radius) !important;
    border: 1px solid var(--border-light) !important;
    box-shadow: var(--shadow-sm) !important;
    padding: 1rem 1.2rem !important;
    margin-bottom: 0.6rem !important;
    background: var(--bg-card) !important;
}

/* ── Chat input ────────────────────────────────────────────────────── */
[data-testid="stChatInput"] textarea {
    border-radius: var(--radius) !important;
    border: 2px solid var(--border) !important;
    padding: 0.8rem 1rem !important;
    transition: border-color 0.2s ease !important;
}
[data-testid="stChatInput"] textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(74,144,217,0.12) !important;
}

/* ── Text inputs & selects ─────────────────────────────────────────── */
.stTextInput input,
.stSelectbox [data-baseweb="select"],
.stTextArea textarea {
    border-radius: var(--radius-sm) !important;
    border: 1px solid var(--border) !important;
    transition: border-color 0.2s ease !important;
}
.stTextInput input:focus,
.stTextArea textarea:focus {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px rgba(74,144,217,0.10) !important;
}

/* ── File uploader ─────────────────────────────────────────────────── */
[data-testid="stFileUploader"] {
    border-radius: var(--radius) !important;
}
[data-testid="stFileUploader"] section {
    border-radius: var(--radius) !important;
    border: 2px dashed var(--border) !important;
    transition: border-color 0.2s ease !important;
}
[data-testid="stFileUploader"] section:hover {
    border-color: var(--accent) !important;
}

/* ── Alerts (info / success / warning / error) ─────────────────────── */
[data-testid="stAlert"] {
    border-radius: var(--radius-sm) !important;
    border-left-width: 4px !important;
    font-size: 0.9rem !important;
}

/* ── Metrics ───────────────────────────────────────────────────────── */
[data-testid="stMetric"] {
    background: var(--bg-card);
    border-radius: var(--radius-sm);
    padding: 0.8rem 1rem;
    border: 1px solid var(--border-light);
    box-shadow: var(--shadow-sm);
}
[data-testid="stMetric"] [data-testid="stMetricValue"] {
    color: var(--accent) !important;
    font-weight: 700;
}

/* ── Dataframe ─────────────────────────────────────────────────────── */
[data-testid="stDataFrame"] {
    border-radius: var(--radius) !important;
    overflow: hidden;
    box-shadow: var(--shadow-sm);
    border: 1px solid var(--border-light);
}

/* ── Code blocks ───────────────────────────────────────────────────── */
pre, code {
    border-radius: var(--radius-sm) !important;
}

/* ── Progress bar ──────────────────────────────────────────────────── */
.stProgress > div > div {
    border-radius: 20px !important;
    background: linear-gradient(90deg, var(--accent) 0%, #6fb3f2 100%) !important;
}

/* ── Captions ──────────────────────────────────────────────────────── */
.stCaption, [data-testid="stCaptionContainer"] {
    color: var(--text-muted) !important;
    font-size: 0.82rem !important;
}

/* ── Main title area ──────────────────────────────────────────────── */
.app-header {
    background: linear-gradient(135deg, #2c3e50 0%, #4a90d9 100%);
    border-radius: var(--radius);
    padding: 1.6rem 2rem;
    margin-bottom: 1.2rem;
    color: #ffffff;
    box-shadow: var(--shadow-md);
}
.app-header h1 {
    margin: 0;
    font-size: 1.8rem;
    font-weight: 700;
    letter-spacing: -0.03em;
}
.app-header p {
    margin: 0.4rem 0 0 0;
    opacity: 0.85;
    font-size: 0.95rem;
}

/* ── Login card ────────────────────────────────────────────────────── */
.login-card {
    background: var(--bg-card);
    border-radius: 16px;
    padding: 2.5rem 2rem;
    box-shadow: 0 8px 30px rgba(0,0,0,0.08);
    border: 1px solid var(--border-light);
    margin-top: 3rem;
}
.login-card h2 {
    color: var(--text-primary);
    font-weight: 700;
    margin-bottom: 0.3rem;
}
.login-subtitle {
    color: var(--text-muted);
    font-size: 0.9rem;
    margin-bottom: 1.5rem;
}

/* ── Section headers in main area ─────────────────────────────────── */
.main h2, .main h3 {
    color: var(--text-primary);
    font-weight: 600;
    letter-spacing: -0.02em;
}

/* ── Scrollbar ─────────────────────────────────────────────────────── */
::-webkit-scrollbar {
    width: 6px;
    height: 6px;
}
::-webkit-scrollbar-track {
    background: transparent;
}
::-webkit-scrollbar-thumb {
    background: var(--border);
    border-radius: 10px;
}
::-webkit-scrollbar-thumb:hover {
    background: var(--text-muted);
}

/* ── Token-usage pill (custom) ─────────────────────────────────────── */
.token-pill {
    display: inline-block;
    background: var(--accent-light);
    color: var(--accent);
    border-radius: 20px;
    padding: 0.25rem 0.8rem;
    font-size: 0.78rem;
    font-weight: 500;
    margin-top: 0.3rem;
}

/* ── Pipeline badge ────────────────────────────────────────────────── */
.pipeline-badge {
    display: inline-block;
    border-radius: 20px;
    padding: 0.2rem 0.75rem;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.03em;
}
.pipeline-badge.v3 {
    background: var(--success-bg);
    color: var(--success);
    border: 1px solid var(--success);
}
.pipeline-badge.v2 {
    background: var(--info-bg);
    color: var(--accent);
    border: 1px solid var(--accent);
}

/* ── Hide default Streamlit title (we use custom header) ───────────── */
.main .block-container { padding-top: 1rem; }
</style>
"""

st.markdown(_CUSTOM_CSS, unsafe_allow_html=True)


def check_password():
    """Returns True if the user supplied the correct password."""
    if "password_correct" in st.session_state and st.session_state["password_correct"]:
        return True

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            '<div class="login-card">'
            '<h2 style="text-align:center;">🔒 Login Required</h2>'
            '<p class="login-subtitle" style="text-align:center;">'
            'Sign in to access the Meeting Intelligence System</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submit = st.form_submit_button("Access", use_container_width=True)
            if submit:
                if username == "meeting" and password == "zaq1@#Cde3":
                    st.session_state["password_correct"] = True
                    st.rerun()
                else:
                    st.error("😕 User not known or password incorrect")
    return False


if not check_password():
    st.stop()

st.markdown(
    f'<div class="app-header">'
    f'<h1>🎙️ {settings.app_name}</h1>'
    f'<p>Intelligent meeting analysis powered by LangGraph</p>'
    f'</div>',
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# API helpers — v2
# ---------------------------------------------------------------------------

def _status_url(meeting_id: str) -> str:
    """Build the status-polling URL for a given meeting_id."""
    return f"{API_BASE}{APIEndpoints.STATUS.replace('{meeting_id}', meeting_id)}"


def fetch_meetings() -> List[Dict[str, Any]]:
    """Fetch all meetings from the API."""
    try:
        resp = httpx.get(
            f"{API_BASE}{APIEndpoints.MEETINGS}",
            timeout=Defaults.REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json()
    except httpx.RequestError as e:
        logger.error("fetch_meetings_failed", error=str(e))
    return []


def upload_transcript(file) -> Optional[str]:
    """Upload transcript via v2 async endpoint.

    POSTs to /api/v2/upload (returns 202), then polls /api/status/{id}
    until the ingestion reaches READY or FAILED.

    Returns:
        meeting_id on success, None on failure.
    """
    try:
        filename = InputValidator.sanitize_filename(file.name)
        InputValidator.validate_file_extension(filename, ["txt"])
        logger.info("upload_started", filename=filename, size_bytes=len(file.getvalue()))

        with st.spinner("Uploading transcript…"):
            files = {"file": (filename, file.getvalue(), "text/plain")}
            resp = httpx.post(
                f"{API_BASE}{APIEndpoints.V2_UPLOAD}",
                files=files,
                timeout=Defaults.REQUEST_TIMEOUT,
            )

        if resp.status_code not in (200, 202):
            error_body = resp.json() if "json" in resp.headers.get("content-type", "") else resp.text
            logger.error("upload_api_error", status=resp.status_code, error=error_body)
            st.error(f"❌ API Error: {resp.status_code}")
            return None

        result = resp.json()
        meeting_id = result.get("meeting_id")
        st.info(f"📤 Accepted — meeting_id: `{meeting_id}`")

        # Poll for ingestion to complete
        status_url = _status_url(meeting_id)
        progress = st.progress(0, text="Ingestion in progress…")
        for i in range(60):
            time.sleep(2)
            progress.progress(min((i + 1) * 3, 95), text="Ingestion in progress…")
            try:
                poll = httpx.get(status_url, timeout=Defaults.REQUEST_TIMEOUT)
                if poll.status_code == 200:
                    data = poll.json()
                    ing_status = data.get("status", "")
                    if ing_status == "READY":
                        progress.progress(100, text="Done!")
                        increment_index_count()
                        st.success(f"✅ Ingestion complete — {meeting_id}")
                        logger.info("upload_success", meeting_id=meeting_id)
                        return meeting_id
                    if ing_status == "FAILED":
                        progress.empty()
                        err = data.get("error", "unknown error")
                        st.error(f"❌ Ingestion failed: {err}")
                        logger.error("ingestion_failed", meeting_id=meeting_id, error=err)
                        return None
            except httpx.RequestError:
                pass  # transient — retry

        progress.empty()
        st.warning("⏱️ Ingestion still in progress. Check the Meetings tab later.")
        return meeting_id

    except ValueError as e:
        logger.warning("upload_validation_failed", error=str(e))
        st.error(f"❌ Invalid file: {e}")
        return None
    except httpx.RequestError as e:
        logger.error("upload_connection_failed", error=str(e))
        st.error(f"❌ Connection failed: {e}")
        return None
    except Exception as e:
        logger.error("upload_unexpected_error", error=str(e))
        st.error(f"❌ Unexpected error: {e}")
        return None


def run_evaluation(
    question: str,
    meeting_ids: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Run DeepEval evaluation on a Q&A pair via the API."""
    try:
        payload: Dict[str, Any] = {"question": question}
        if meeting_ids:
            payload["meeting_ids"] = meeting_ids

        resp = httpx.post(
            f"{API_BASE}{APIEndpoints.V2_EVALUATE}",
            json=payload,
            timeout=Defaults.REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json()

        logger.error("eval_api_error", status=resp.status_code)
        st.error(f"Evaluation failed: {resp.status_code}")
        return None
    except httpx.RequestError as e:
        logger.error("eval_connection_failed", error=str(e))
        st.error(f"Evaluation connection failed: {e}")
        return None


def fetch_eval_history(
    meeting_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Fetch historical evaluation results."""
    try:
        params: Dict[str, Any] = {"limit": limit}
        if meeting_id:
            params["meeting_id"] = meeting_id

        resp = httpx.get(
            f"{API_BASE}{APIEndpoints.V2_EVAL_HISTORY}",
            params=params,
            timeout=Defaults.REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            return resp.json()
    except httpx.RequestError as e:
        logger.error("eval_history_failed", error=str(e))
    return []


def query_meeting(
    query_text: str,
    meeting_ids: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """Execute grounded Q&A via v2 query endpoint.

    Returns:
        CitedAnswer dict: {answer, citations, retrieved_context,
                           meeting_ids, latency_ms}
    """
    try:
        query_text = InputValidator.validate_non_empty_string(query_text, "query")

        logger.info(
            "query_started",
            query_length=len(query_text),
            meeting_ids=meeting_ids,
        )

        payload: Dict[str, Any] = {"question": query_text}
        if meeting_ids:
            payload["meeting_ids"] = meeting_ids

        resp = httpx.post(
            f"{API_BASE}{APIEndpoints.V2_QUERY}",
            json=payload,
            timeout=Defaults.REQUEST_TIMEOUT,
        )

        if resp.status_code == 200:
            result = resp.json()
            logger.info(
                "query_success",
                citations_count=len(result.get("citations", [])),
                latency_ms=result.get("latency_ms"),
            )
            return result

        error_body = resp.json() if "json" in resp.headers.get("content-type", "") else resp.text
        logger.error("query_api_error", status=resp.status_code, error=error_body)
        st.error(f"❌ Query failed: {resp.status_code}")
        return None

    except ValueError as e:
        logger.warning("query_validation_failed", error=str(e))
        st.error(f"❌ Invalid input: {e}")
        return None
    except httpx.RequestError as e:
        logger.error("query_connection_failed", error=str(e))
        st.error(f"❌ API connection failed: {e}")
        return None
    except Exception as e:
        logger.error("query_unexpected_error", error=str(e))
        st.error(f"❌ Unexpected error: {e}")
        return None


# ---------------------------------------------------------------------------
# API helpers — v3 (LangGraph)
# ---------------------------------------------------------------------------

def upload_transcript_v3(file) -> Optional[str]:
    """Upload transcript via v3 LangGraph ingestion endpoint.

    POSTs to /api/v3/upload (returns 202), then polls /api/v2/status/{id}
    until the ingestion reaches READY or FAILED.

    Returns:
        meeting_id on success, None on failure.
    """
    try:
        filename = InputValidator.sanitize_filename(file.name)
        InputValidator.validate_file_extension(filename, ["txt"])
        logger.info("v3_upload_started", filename=filename, size_bytes=len(file.getvalue()))

        with st.spinner("Uploading transcript (v3 LangGraph pipeline)…"):
            files = {"file": (filename, file.getvalue(), "text/plain")}
            resp = httpx.post(
                f"{API_BASE}{APIEndpoints.V3_UPLOAD}",
                files=files,
                timeout=Defaults.REQUEST_TIMEOUT,
            )

        if resp.status_code not in (200, 202):
            error_body = resp.json() if "json" in resp.headers.get("content-type", "") else resp.text
            logger.error("v3_upload_api_error", status=resp.status_code, error=error_body)
            st.error(f"❌ API Error: {resp.status_code}")
            return None

        result = resp.json()
        meeting_id = result.get("meeting_id")
        st.info(f"📤 Accepted (v3 LangGraph) — meeting_id: `{meeting_id}`")

        # Poll for ingestion to complete (same status endpoint)
        status_url = _status_url(meeting_id)
        progress = st.progress(0, text="LangGraph ingestion in progress…")
        for i in range(60):
            time.sleep(2)
            progress.progress(min((i + 1) * 3, 95), text="LangGraph ingestion in progress…")
            try:
                poll = httpx.get(status_url, timeout=Defaults.REQUEST_TIMEOUT)
                if poll.status_code == 200:
                    data = poll.json()
                    ing_status = data.get("status", "")
                    if ing_status == "READY":
                        progress.progress(100, text="Done!")
                        increment_index_count()
                        st.success(f"✅ LangGraph ingestion complete — {meeting_id}")
                        logger.info("v3_upload_success", meeting_id=meeting_id)
                        return meeting_id
                    if ing_status == "FAILED":
                        progress.empty()
                        err = data.get("error", "unknown error")
                        st.error(f"❌ Ingestion failed: {err}")
                        logger.error("v3_ingestion_failed", meeting_id=meeting_id, error=err)
                        return None
            except httpx.RequestError:
                pass  # transient — retry

        progress.empty()
        st.warning("⏱️ LangGraph ingestion still running. Check the Meetings tab later.")
        return meeting_id

    except ValueError as e:
        logger.warning("v3_upload_validation_failed", error=str(e))
        st.error(f"❌ Invalid file: {e}")
        return None
    except httpx.RequestError as e:
        logger.error("v3_upload_connection_failed", error=str(e))
        st.error(f"❌ Connection failed: {e}")
        return None
    except Exception as e:
        logger.error("v3_upload_unexpected_error", error=str(e))
        st.error(f"❌ Unexpected error: {e}")
        return None


def query_meeting_v3(
    query_text: str,
    meeting_ids: Optional[List[str]] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Execute grounded Q&A via v3 LangGraph query endpoint.

    Returns:
        CitedAnswer dict: {answer, citations, retrieved_context,
                           meeting_ids, latency_ms, prompt_tokens,
                           completion_tokens, total_tokens,
                           estimated_cost_usd, pipeline}
    """
    try:
        query_text = InputValidator.validate_non_empty_string(query_text, "query")

        logger.info(
            "v3_query_started",
            query_length=len(query_text),
            meeting_ids=meeting_ids,
            session_id=session_id,
        )

        payload: Dict[str, Any] = {"question": query_text}
        if meeting_ids:
            payload["meeting_ids"] = meeting_ids
        if session_id:
            payload["session_id"] = session_id
        if user_id:
            payload["user_id"] = user_id

        resp = httpx.post(
            f"{API_BASE}{APIEndpoints.V3_QUERY}",
            json=payload,
            timeout=Defaults.REQUEST_TIMEOUT,
        )

        if resp.status_code == 200:
            result = resp.json()
            logger.info(
                "v3_query_success",
                citations_count=len(result.get("citations", [])),
                latency_ms=result.get("latency_ms"),
                total_tokens=result.get("total_tokens"),
            )
            return result

        error_body = resp.json() if "json" in resp.headers.get("content-type", "") else resp.text
        logger.error("v3_query_api_error", status=resp.status_code, error=error_body)
        st.error(f"❌ Query failed: {resp.status_code}")
        return None

    except ValueError as e:
        logger.warning("v3_query_validation_failed", error=str(e))
        st.error(f"❌ Invalid input: {e}")
        return None
    except httpx.RequestError as e:
        logger.error("v3_query_connection_failed", error=str(e))
        st.error(f"❌ API connection failed: {e}")
        return None
    except Exception as e:
        logger.error("v3_query_unexpected_error", error=str(e))
        st.error(f"❌ Unexpected error: {e}")
        return None


def fetch_chat_sessions(user_id: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch chat sessions for a user from the v3 API."""
    try:
        params: Dict[str, Any] = {"limit": limit}
        if user_id:
            params["user_id"] = user_id

        resp = httpx.get(
            f"{API_BASE}{APIEndpoints.V3_CHAT_SESSIONS}",
            params=params,
            timeout=Defaults.REQUEST_TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            return data.get("sessions", [])
    except httpx.RequestError as e:
        logger.error("fetch_chat_sessions_failed", error=str(e))
    return []


def fetch_chat_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Fetch full chat session with all turns."""
    try:
        url = f"{API_BASE}{APIEndpoints.V3_CHAT_HISTORY.replace('{session_id}', session_id)}"
        resp = httpx.get(url, timeout=Defaults.REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
    except httpx.RequestError as e:
        logger.error("fetch_chat_session_failed", error=str(e))
    return None


def fetch_user_profile(user_id: str) -> Optional[Dict[str, Any]]:
    """Fetch user memory profile from the v3 API."""
    try:
        url = f"{API_BASE}{APIEndpoints.V3_USER_PROFILE.replace('{user_id}', user_id)}"
        resp = httpx.get(url, timeout=Defaults.REQUEST_TIMEOUT)
        if resp.status_code == 200:
            return resp.json()
    except httpx.RequestError as e:
        logger.error("fetch_user_profile_failed", error=str(e))
    return None


def fetch_graph_mermaid(graph_name: str) -> Optional[str]:
    """Fetch Mermaid diagram source for a LangGraph pipeline."""
    try:
        url = f"{API_BASE}{APIEndpoints.V3_GRAPH_VIZ.replace('{graph_name}', graph_name)}"
        resp = httpx.get(url, timeout=Defaults.REQUEST_TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("mermaid")
    except httpx.RequestError as e:
        logger.error("fetch_graph_mermaid_failed", error=str(e))
    return None


# ---------------------------------------------------------------------------
# Sidebar — pipeline toggle, user identity, sessions, upload, meeting selector
# ---------------------------------------------------------------------------

with st.sidebar:
    # Pipeline toggle
    st.header("⚙️ Pipeline")
    pipeline = st.radio(
        "Processing pipeline",
        options=["v2 (Legacy)", "v3 (LangGraph)"],
        index=1,
        help="v3 uses LangGraph with persistent chat, semantic cache, and token tracking.",
    )
    use_v3 = pipeline.startswith("v3")
    st.session_state["use_v3"] = use_v3

    if use_v3:
        st.markdown(
            '<span class="pipeline-badge v3">✦ LangGraph Active</span>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<span class="pipeline-badge v2">📦 Legacy Active</span>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    # User identity (for v3 chat history & memory)
    if use_v3:
        st.header("👤 User Identity")
        user_id = st.text_input(
            "User ID",
            value=st.session_state.get("user_id", "meeting"),
            help="Used for persistent chat sessions and user memory.",
        )
        st.session_state["user_id"] = user_id

        st.markdown("---")

        # Session management
        st.header("💬 Chat Sessions")
        if st.button("➕ New Session", use_container_width=True):
            st.session_state["session_id"] = str(uuid.uuid4())
            st.session_state["messages"] = []
            st.rerun()

        # Show current session
        current_session = st.session_state.get("session_id", "")
        if current_session:
            st.caption(f"Session: `{current_session[:12]}…`")

        # Load previous sessions
        sessions = fetch_chat_sessions(user_id=user_id, limit=10)
        if sessions:
            session_labels = {
                f"Session {s['session_id'][:8]}… ({s.get('turns', 0)} turns)": s["session_id"]
                for s in sessions
            }
            selected_session = st.selectbox(
                "Resume session",
                options=["— Current session —"] + list(session_labels.keys()),
            )
            if selected_session and selected_session != "— Current session —":
                chosen_id = session_labels[selected_session]
                if chosen_id != st.session_state.get("session_id"):
                    st.session_state["session_id"] = chosen_id
                    # Load turns from the backend
                    session_data = fetch_chat_session(chosen_id)
                    if session_data and session_data.get("turns"):
                        loaded: List[Dict[str, Any]] = []
                        for turn in session_data["turns"]:
                            loaded.append({"role": "user", "content": turn.get("question", "")})
                            loaded.append({
                                "role": "assistant",
                                "content": turn.get("answer", ""),
                                "citations": turn.get("citations", []),
                                "token_usage": {
                                    "prompt_tokens": turn.get("prompt_tokens", 0),
                                    "completion_tokens": turn.get("completion_tokens", 0),
                                    "total_tokens": turn.get("total_tokens", 0),
                                    "estimated_cost_usd": turn.get("estimated_cost_usd", 0),
                                },
                            })
                        st.session_state["messages"] = loaded
                    else:
                        st.session_state["messages"] = []
                    st.rerun()

        st.markdown("---")

    # Upload
    st.header("📤 Upload Transcript")

    index_count = get_index_count()
    st.metric("📊 Documents Indexed", index_count)

    uploaded_file = st.file_uploader(
        "Choose a meeting transcript (.txt)", type=["txt"]
    )

    if uploaded_file and st.button("🚀 Index Meeting", use_container_width=True):
        if use_v3:
            meeting_id = upload_transcript_v3(uploaded_file)
        else:
            meeting_id = upload_transcript(uploaded_file)
        if meeting_id:
            st.session_state["meeting_id"] = meeting_id
            st.rerun()

    st.markdown("---")
    st.header("📂 Select Meeting")

    meetings = fetch_meetings()
    if meetings:
        options = {
            f"{m['title']} ({m['status']})": m["meeting_id"] for m in meetings
        }
        selected_label = st.selectbox(
            "Available meetings",
            options=["— All meetings —"] + list(options.keys()),
        )
        if selected_label and selected_label != "— All meetings —":
            st.session_state["meeting_id"] = options[selected_label]
        elif selected_label == "— All meetings —":
            st.session_state.pop("meeting_id", None)
    else:
        st.caption("No meetings found. Upload a transcript to get started.")

    st.markdown("---")
    if st.button("🗑️ Reset Local State", use_container_width=True):
        if nuclear_reset():
            st.session_state["messages"] = []
            st.session_state["session_id"] = str(uuid.uuid4())
            st.success("Local state reset.")
            st.rerun()


# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state["session_id"] = str(uuid.uuid4())
if "user_id" not in st.session_state:
    st.session_state["user_id"] = "meeting"
if "use_v3" not in st.session_state:
    st.session_state["use_v3"] = True


# ---------------------------------------------------------------------------
# Main layout — Chat + Meetings + Monitoring + Pipelines + Profile tabs
# ---------------------------------------------------------------------------

use_v3 = st.session_state.get("use_v3", True)

tab_chat, tab_meetings, tab_monitoring, tab_graph, tab_profile = st.tabs(
    ["💬 Chat", "📋 Meetings", "📊 Monitoring", "🔀 Pipelines", "👤 Profile"]
)

# ===== Chat tab =====
with tab_chat:
    active_meeting = st.session_state.get("meeting_id")
    if active_meeting:
        st.info(f"📌 Scoped to meeting: `{active_meeting}`")
    else:
        st.caption("Querying across all meetings. Select one in the sidebar to narrow results.")

    if use_v3:
        v3_cols = st.columns([3, 1])
        with v3_cols[0]:
            st.caption(
                f"🔀 LangGraph pipeline · Session "
                f"`{st.session_state.get('session_id', '')[:12]}…`"
            )
        with v3_cols[1]:
            st.caption(f"👤 {st.session_state.get('user_id', 'anonymous')}")

    # Render chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant":
                if message.get("citations"):
                    with st.expander("📚 Citations"):
                        for c in message["citations"]:
                            st.markdown(
                                f"**{c['speaker']}** "
                                f"({c['timestamp_start']}–{c['timestamp_end']})  \n"
                                f"> {c['snippet']}"
                            )
                # Token usage (v3 only)
                if message.get("token_usage"):
                    tu = message["token_usage"]
                    tok_parts = []
                    if tu.get("prompt_tokens"):
                        tok_parts.append(f"Prompt: {tu['prompt_tokens']}")
                    if tu.get("completion_tokens"):
                        tok_parts.append(f"Completion: {tu['completion_tokens']}")
                    if tu.get("total_tokens"):
                        tok_parts.append(f"Total: {tu['total_tokens']}")
                    if tu.get("estimated_cost_usd"):
                        tok_parts.append(f"Cost: ${tu['estimated_cost_usd']:.6f}")
                    if tok_parts:
                        st.markdown(
                            f'<span class="token-pill">🪙 {" · ".join(tok_parts)}</span>',
                            unsafe_allow_html=True,
                        )

    # User input
    if prompt := st.chat_input("Ask about the meeting…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("🤔 Thinking…"):
                meeting_ids = [active_meeting] if active_meeting else None
                if use_v3:
                    result = query_meeting_v3(
                        query_text=prompt,
                        meeting_ids=meeting_ids,
                        session_id=st.session_state.get("session_id"),
                        user_id=st.session_state.get("user_id"),
                    )
                else:
                    result = query_meeting(
                        query_text=prompt,
                        meeting_ids=meeting_ids,
                    )

            if result:
                answer = result.get("answer", "No answer generated.")
                citations = result.get("citations", [])
                latency = result.get("latency_ms", 0)

                st.markdown(answer)

                if citations:
                    with st.expander("📚 Citations"):
                        for c in citations:
                            st.markdown(
                                f"**{c['speaker']}** "
                                f"({c['timestamp_start']}–{c['timestamp_end']})  \n"
                                f"> {c['snippet']}"
                            )

                # Token usage display (v3)
                token_usage: Dict[str, Any] = {}
                if use_v3:
                    prompt_tokens = result.get("prompt_tokens", 0)
                    completion_tokens = result.get("completion_tokens", 0)
                    total_tokens = result.get("total_tokens", 0)
                    estimated_cost = result.get("estimated_cost_usd", 0)
                    token_usage = {
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "total_tokens": total_tokens,
                        "estimated_cost_usd": estimated_cost,
                    }

                    tok_parts = []
                    if prompt_tokens:
                        tok_parts.append(f"Prompt: {prompt_tokens}")
                    if completion_tokens:
                        tok_parts.append(f"Completion: {completion_tokens}")
                    if total_tokens:
                        tok_parts.append(f"Total: {total_tokens}")
                    if estimated_cost:
                        tok_parts.append(f"Cost: ${estimated_cost:.6f}")
                    if tok_parts:
                        st.markdown(
                            f'<span class="token-pill">🪙 {" · ".join(tok_parts)}</span>',
                            unsafe_allow_html=True,
                        )

                if latency:
                    st.markdown(
                        f'<span class="token-pill" style="margin-left:0.4rem;">'
                        f'⏱️ {latency:.0f} ms</span>',
                        unsafe_allow_html=True,
                    )

                msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": answer,
                    "citations": citations,
                }
                if token_usage:
                    msg["token_usage"] = token_usage
                st.session_state.messages.append(msg)
            else:
                fallback = "Sorry, I couldn't get a response."
                st.markdown(fallback)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": fallback,
                })

# ===== Meetings tab =====
with tab_meetings:
    st.header("📋 Meeting Inventory")

    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

    meetings = fetch_meetings()
    if not meetings:
        st.info("No meetings found. Upload a transcript to get started.")
    else:
        for m in meetings:
            status_emoji = {
                "READY": "🟢",
                "PENDING": "🟡",
                "FAILED": "🔴",
            }.get(m.get("status", ""), "⚪")

            with st.container(border=True):
                cols = st.columns([3, 2, 1, 1])
                cols[0].markdown(f"**{m.get('title', 'Untitled')}**")
                cols[1].caption(m.get("date", "—"))
                cols[2].markdown(f"{status_emoji} {m.get('status', '?')}")
                if cols[3].button("Select", key=m["meeting_id"]):
                    st.session_state["meeting_id"] = m["meeting_id"]
                    st.rerun()

            if m.get("participants"):
                st.caption(f"👥 {', '.join(m['participants'])}")

# ===== Monitoring tab =====
with tab_monitoring:
    st.header("📊 RAG Quality Monitoring")
    st.caption(
        "Run DeepEval Faithfulness & Answer Relevancy metrics on queries. "
        "Results are stored locally and plotted over time."
    )

    # --- Run a new evaluation ---
    st.subheader("🧪 Run Evaluation")
    eval_question = st.text_input(
        "Enter a question to evaluate",
        placeholder="What were the main decisions made in this meeting?",
        key="eval_question",
    )
    eval_meeting = st.session_state.get("meeting_id")
    if eval_meeting:
        st.info(f"📌 Evaluating against meeting: `{eval_meeting}`")

    if st.button("🚀 Run Evaluation", use_container_width=True, disabled=not eval_question):
        with st.spinner("Running DeepEval metrics (this may take 30-60s)…"):
            eval_ids = [eval_meeting] if eval_meeting else None
            eval_result = run_evaluation(eval_question, meeting_ids=eval_ids)

        if eval_result:
            st.success("Evaluation complete!")
            col1, col2, col3 = st.columns(3)
            col1.metric(
                "Faithfulness",
                f"{(eval_result.get('faithfulness') or 0):.2f}",
            )
            col2.metric(
                "Answer Relevancy",
                f"{(eval_result.get('answer_relevancy') or 0):.2f}",
            )
            col3.metric(
                "Overall Score",
                f"{(eval_result.get('overall_score') or 0):.2f}",
            )

            with st.expander("📝 Evaluation Details"):
                st.json(eval_result)

    st.markdown("---")

    # --- Historical results ---
    st.subheader("📈 Evaluation History")

    if st.button("🔄 Refresh History"):
        st.cache_data.clear()

    history_meeting = eval_meeting if eval_meeting else None
    history = fetch_eval_history(meeting_id=history_meeting, limit=50)

    if not history:
        st.info("No evaluation history yet. Run an evaluation above to get started.")
    else:
        # Summary metrics
        st.caption(f"Showing {len(history)} most recent evaluations")

        faith_scores = [h["faithfulness"] for h in history if h.get("faithfulness") is not None]
        relev_scores = [h["answer_relevancy"] for h in history if h.get("answer_relevancy") is not None]
        overall_scores = [h["overall_score"] for h in history if h.get("overall_score") is not None]

        if overall_scores:
            avg_col1, avg_col2, avg_col3, avg_col4 = st.columns(4)
            avg_col1.metric("Avg Faithfulness", f"{sum(faith_scores) / len(faith_scores):.2f}" if faith_scores else "—")
            avg_col2.metric("Avg Relevancy", f"{sum(relev_scores) / len(relev_scores):.2f}" if relev_scores else "—")
            avg_col3.metric("Avg Overall", f"{sum(overall_scores) / len(overall_scores):.2f}")
            avg_col4.metric("Total Evals", len(history))

        # Score trend chart
        st.subheader("Score Trends")

        # Build chart data — most recent last (history is newest-first)
        chart_history = list(reversed(history))
        chart_data = {
            "Evaluation #": list(range(1, len(chart_history) + 1)),
            "Faithfulness": [h.get("faithfulness") or 0 for h in chart_history],
            "Answer Relevancy": [h.get("answer_relevancy") or 0 for h in chart_history],
            "Overall": [h.get("overall_score") or 0 for h in chart_history],
        }

        import pandas as pd
        df = pd.DataFrame(chart_data)
        df = df.set_index("Evaluation #")

        st.line_chart(df, height=350)

        # Score distribution
        st.subheader("Score Distribution")
        dist_col1, dist_col2 = st.columns(2)

        with dist_col1:
            if faith_scores:
                st.caption("Faithfulness Distribution")
                faith_df = pd.DataFrame({"Faithfulness": faith_scores})
                st.bar_chart(faith_df["Faithfulness"].value_counts().sort_index(), height=250)

        with dist_col2:
            if relev_scores:
                st.caption("Answer Relevancy Distribution")
                relev_df = pd.DataFrame({"Answer Relevancy": relev_scores})
                st.bar_chart(relev_df["Answer Relevancy"].value_counts().sort_index(), height=250)

        # Detailed results table
        st.subheader("📋 Detailed Results")
        table_data = []
        for h in history:
            table_data.append({
                "Time": h.get("evaluated_at", "—")[:19],
                "Question": h.get("question", "")[:80],
                "Faithfulness": f"{h.get('faithfulness', 0):.2f}" if h.get("faithfulness") is not None else "—",
                "Relevancy": f"{h.get('answer_relevancy', 0):.2f}" if h.get("answer_relevancy") is not None else "—",
                "Overall": f"{h.get('overall_score', 0):.2f}" if h.get("overall_score") is not None else "—",
                "Latency (ms)": f"{h.get('latency_ms', 0):.0f}",
            })

        st.dataframe(
            pd.DataFrame(table_data),
            use_container_width=True,
            hide_index=True,
        )

# ===== Pipeline Visualization tab =====
with tab_graph:
    st.header("🔀 LangGraph Pipeline Visualization")
    st.caption(
        "View the Mermaid diagrams for the LangGraph ingestion and query pipelines."
    )

    graph_choice = st.radio(
        "Select pipeline",
        options=["ingestion", "query"],
        horizontal=True,
    )

    if st.button("📊 Load Diagram", use_container_width=True):
        with st.spinner("Fetching pipeline diagram…"):
            mermaid_src = fetch_graph_mermaid(graph_choice)

        if mermaid_src:
            st.subheader(f"{graph_choice.title()} Pipeline")

            # Render as code block (Mermaid source)
            st.code(mermaid_src, language="mermaid")

            with st.expander("📋 Raw Mermaid Source"):
                st.text(mermaid_src)
        else:
            st.warning(
                "Could not load the pipeline diagram. "
                "Ensure the API is running with the v3 pipeline enabled."
            )

# ===== User Profile tab =====
with tab_profile:
    st.header("👤 User Memory Profile")

    if not use_v3:
        st.info("Switch to the v3 pipeline in the sidebar to enable user memory features.")
    else:
        profile_user = st.session_state.get("user_id", "meeting")
        st.caption(f"Showing profile for user: **{profile_user}**")

        if st.button("🔄 Load Profile", use_container_width=True):
            with st.spinner("Loading user profile…"):
                profile = fetch_user_profile(profile_user)

            if profile:
                facts = profile.get("facts", [])
                preferences = profile.get("preferences", {})

                col_facts, col_prefs = st.columns(2)

                with col_facts:
                    st.subheader("📝 Known Facts")
                    if facts:
                        for fact in facts:
                            with st.container(border=True):
                                st.markdown(f"**{fact.get('category', 'general')}**")
                                st.write(fact.get("content", ""))
                                st.caption(f"Confidence: {fact.get('confidence', 0):.0%}")
                    else:
                        st.caption(
                            "No facts recorded yet. Chat with the system to "
                            "build your profile."
                        )

                with col_prefs:
                    st.subheader("⚙️ Preferences")
                    if preferences:
                        for key, value in preferences.items():
                            st.markdown(f"**{key}:** {value}")
                    else:
                        st.caption("No preferences recorded yet.")

                st.markdown("---")
                st.caption(
                    f"User ID: `{profile.get('user_id', profile_user)}` · "
                    f"Facts: {len(facts)} · "
                    f"Last updated: {profile.get('updated_at', '—')}"
                )
            else:
                st.info(
                    "No profile found. Your profile builds automatically "
                    "as you interact with the system."
                )
