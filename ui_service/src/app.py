"""
Streamlit UI for Meeting Intelligence System v2.

Provides transcript upload (async), meeting browsing, grounded Q&A
with citations, and RAG quality monitoring against the v2 FastAPI backend.
"""

import streamlit as st
import httpx
import json
import os
import time
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

st.set_page_config(page_title=settings.app_name, layout="wide")


def check_password():
    """Returns True if the user supplied the correct password."""
    if "password_correct" in st.session_state and st.session_state["password_correct"]:
        return True

    _, col, _ = st.columns([1, 2, 1])
    with col:
        st.markdown(
            "<h2 style='text-align: center;'>🔒 Login Required</h2>",
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

st.title(f"🎙️ {settings.app_name}")
st.markdown("---")


# ---------------------------------------------------------------------------
# API helpers
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
# Sidebar — upload & meeting selector
# ---------------------------------------------------------------------------

with st.sidebar:
    st.header("📤 Upload Transcript")

    index_count = get_index_count()
    st.metric("📊 Documents Indexed", index_count)

    uploaded_file = st.file_uploader(
        "Choose a meeting transcript (.txt)", type=["txt"]
    )

    if uploaded_file and st.button("🚀 Index Meeting", use_container_width=True):
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
            st.success("Local state reset.")
            st.rerun()


# ---------------------------------------------------------------------------
# Session state init
# ---------------------------------------------------------------------------

if "messages" not in st.session_state:
    st.session_state.messages = []

# ---------------------------------------------------------------------------
# Main layout — Chat + Meetings + Monitoring tabs
# ---------------------------------------------------------------------------

tab_chat, tab_meetings, tab_monitoring = st.tabs(["💬 Chat", "📋 Meetings", "📊 Monitoring"])

# ===== Chat tab =====
with tab_chat:
    active_meeting = st.session_state.get("meeting_id")
    if active_meeting:
        st.info(f"📌 Scoped to meeting: `{active_meeting}`")
    else:
        st.caption("Querying across all meetings. Select one in the sidebar to narrow results.")

    # Chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message["role"] == "assistant" and message.get("citations"):
                with st.expander("📚 Citations"):
                    for c in message["citations"]:
                        st.markdown(
                            f"**{c['speaker']}** "
                            f"({c['timestamp_start']}–{c['timestamp_end']})  \n"
                            f"> {c['snippet']}"
                        )

    # User input
    if prompt := st.chat_input("Ask about the meeting…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("🤔 Thinking…"):
                meeting_ids = [active_meeting] if active_meeting else None
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

                if latency:
                    st.caption(f"⏱️ {latency:.0f} ms")

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer,
                    "citations": citations,
                })
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


