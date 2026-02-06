"""
Streamlit UI for Meeting Intelligence System.
Provides transcript upload and RAG query interface.
"""

import streamlit as st
import httpx
import pandas as pd
import json
import os
import time
import shutil
from typing import Optional, Dict, Any, List
from datetime import datetime

from shared_utils.config_loader import get_settings
from shared_utils.logging_utils import ContextualLogger, get_scoped_logger
from shared_utils.constants import LogScope, APIEndpoints, Defaults
from shared_utils.error_handler import handle_error
from shared_utils.validation import InputValidator


# Initialize configuration and logging
settings = get_settings()
logger = ContextualLogger(scope=LogScope.UI)

# API endpoint configuration
API_BASE = settings.get_api_base_url()

# Index counter file path
INDEX_COUNT_FILE = "data/index_count.json"


def get_index_count() -> int:
    """Get the current count of indexed documents."""
    try:
        if os.path.exists(INDEX_COUNT_FILE):
            with open(INDEX_COUNT_FILE, 'r') as f:
                data = json.load(f)
                return data.get("count", 0)
    except Exception:
        pass
    return 0


def increment_index_count() -> int:
    """Increment the index count and return the new count."""
    try:
        os.makedirs(os.path.dirname(INDEX_COUNT_FILE), exist_ok=True)
        count = get_index_count() + 1
        with open(INDEX_COUNT_FILE, 'w') as f:
            json.dump({"count": count}, f)
        return count
    except Exception as e:
        logger.error("index_count_update_failed", error=str(e))
        return get_index_count()


def reset_database() -> bool:
    """Reset/cleanup the entire database (LanceDB, metrics, counter)."""
    try:
        # Reset LanceDB
        lancedb_path = "data/lancedb"
        if os.path.exists(lancedb_path):
            shutil.rmtree(lancedb_path)
            logger.info("lancedb_cleared")
        
        # Reset metrics
        metrics_path = "data/metrics/historical_metrics.json"
        if os.path.exists(metrics_path):
            os.makedirs(os.path.dirname(metrics_path), exist_ok=True)
            with open(metrics_path, 'w') as f:
                json.dump([], f)
            logger.info("metrics_cleared")
        
        # Reset index counter
        if os.path.exists(INDEX_COUNT_FILE):
            os.makedirs(os.path.dirname(INDEX_COUNT_FILE), exist_ok=True)
            with open(INDEX_COUNT_FILE, 'w') as f:
                json.dump({"count": 0}, f)
            logger.info("index_counter_reset")
        
        return True
    except Exception as e:
        logger.error("database_reset_failed", error=str(e))
        return False


def nuclear_reset() -> bool:
    """Comprehensive reset including test databases and all cache."""
    try:
        # Clear all LanceDB instances
        for db_path in ["data/lancedb", "data/test_lancedb"]:
            if os.path.exists(db_path):
                shutil.rmtree(db_path)
                logger.info(f"cleared_{db_path}")
        
        # Clear metrics
        metrics_path = "data/metrics/historical_metrics.json"
        os.makedirs(os.path.dirname(metrics_path), exist_ok=True)
        with open(metrics_path, 'w') as f:
            json.dump([], f)
        
        # Clear index counter
        os.makedirs(os.path.dirname(INDEX_COUNT_FILE), exist_ok=True)
        with open(INDEX_COUNT_FILE, 'w') as f:
            json.dump({"count": 0}, f)
        
        # Clear Streamlit cache
        st.cache_data.clear()
        st.cache_resource.clear()
        
        logger.info("nuclear_reset_complete")
        return True
    except Exception as e:
        logger.error("nuclear_reset_failed", error=str(e))
        return False


# Page configuration
st.set_page_config(page_title=settings.app_name, layout="wide")
st.title(f"🎙️ {settings.app_name}")
st.markdown("---")


def upload_transcript(file) -> Optional[str]:
    """Upload and index transcript file.
    
    Args:
        file: Streamlit uploaded file object
    
    Returns:
        Meeting ID if successful, None otherwise
    
    Raises:
        Logs errors to UI and returns None on failure
    """
    try:
        # Validate filename
        filename = InputValidator.sanitize_filename(file.name)
        InputValidator.validate_file_extension(filename, ['txt'])
        
        logger.info("upload_started", filename=filename, size_bytes=len(file.getvalue()))
        
        with st.spinner("Processing..."):
            files = {"file": (filename, file.getvalue(), "text/plain")}
            response = httpx.post(
                f"{API_BASE}{APIEndpoints.UPLOAD}",
                files=files,
                timeout=Defaults.REQUEST_TIMEOUT
            )
            
            if response.status_code == 200:
                result = response.json()
                meeting_id = result.get('meeting_id')
                logger.info("upload_success", meeting_id=meeting_id)
                # Increment the index count
                new_count = increment_index_count()
                st.success(f"✅ Indexed: {meeting_id}")
                st.info(f"📊 Total indexed: {new_count} document(s)")
                return meeting_id
            else:
                error_response = response.json() if response.headers.get('content-type') == 'application/json' else response.text
                logger.error("upload_api_error", status=response.status_code, error=error_response)
                st.error(f"❌ API Error: {response.status_code}")
                return None
    
    except ValueError as e:
        # Validation error
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


def query_meeting(query_text: str, meeting_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Execute RAG query against meeting.
    
    Args:
        query_text: User query
        meeting_id: Optional meeting ID to filter results
    
    Returns:
        Query response dict with answer and sources, or None if failed
    """
    try:
        # Validate query
        query_text = InputValidator.validate_non_empty_string(query_text, "query")
        
        if meeting_id:
            meeting_id = InputValidator.validate_uuid(meeting_id)
        
        logger.info("query_started", query_length=len(query_text), meeting_id=meeting_id)
        
        payload = {
            "query": query_text,
            "meeting_id": meeting_id
        }
        
        response = httpx.post(
            f"{API_BASE}{APIEndpoints.QUERY}",
            json=payload,
            timeout=Defaults.REQUEST_TIMEOUT
        )
        
        if response.status_code == 200:
            result = response.json()
            logger.info("query_success", sources_count=len(result.get('sources', [])))
            return result
        else:
            error_response = response.json() if response.headers.get('content-type') == 'application/json' else response.text
            logger.error("query_api_error", status=response.status_code, error=error_response)
            st.error(f"❌ Query failed: {response.status_code}")
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


# ============================================================================
# Sidebar: Transcript Upload
# ============================================================================
with st.sidebar:
    st.header("📤 Upload Transcript")
    
    # Display index count
    index_count = get_index_count()
    st.metric("📊 Documents Indexed", index_count)
    
    uploaded_file = st.file_uploader("Choose a meeting transcript (.txt)", type=["txt"])
    
    if uploaded_file and st.button("🚀 Index Meeting", use_container_width=True):
        meeting_id = upload_transcript(uploaded_file)
        if meeting_id:
            st.session_state["meeting_id"] = meeting_id
            st.rerun()


# ============================================================================
# Main Chat Interface
# ============================================================================
if "messages" not in st.session_state:
    st.session_state.messages = []
if "eval_history" not in st.session_state:
    st.session_state.eval_history = []

# Main Layout with Tabs
tab_chat, tab_monitor = st.tabs(["💬 Chat", "📊 Monitoring"])

with tab_chat:
    # Display session state if meeting indexed
    if st.session_state.get("meeting_id"):
        st.info(f"📌 Connected to Meeting: {st.session_state['meeting_id']}")

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # User input and query
    if prompt := st.chat_input("Ask about the meeting..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("🤔 Thinking..."):
                result = query_meeting(
                    query_text=prompt,
                    meeting_id=st.session_state.get("meeting_id")
                )
                
                if result:
                    answer = result.get("answer", "No answer generated")
                    st.markdown(answer)
                    st.session_state.messages.append({"role": "assistant", "content": answer})
                    
                    # Store for evaluation
                    st.session_state.eval_history.append({
                        "query": prompt,
                        "response": result
                    })
                    
                    # Display sources if available
                    sources = result.get("sources", [])
                    if sources:
                        with st.expander("📚 Sources"):
                            for source in set(sources):
                                st.write(f"• {source}")

with tab_monitor:
    st.header("📈 System Performance & RAGAS Metrics")
    
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🔄 Refresh Metrics"):
            st.cache_data.clear()
    with col2:
        if st.button("🧪 Run Evaluation on Current Session"):
            if not st.session_state.eval_history:
                st.error("❌ No queries in current session to evaluate.")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                try:
                    # Step 1: Prepare data
                    status_text.text("📋 Preparing evaluation data...")
                    progress_bar.progress(20)
                    
                    queries = [h["query"] for h in st.session_state.eval_history]
                    responses = [h["response"] for h in st.session_state.eval_history]
                    
                    # Step 2: Running evaluation
                    status_text.text("🧠 Running Ragas evaluation...")
                    progress_bar.progress(50)
                    
                    eval_payload = {
                        "queries": queries,
                        "responses": responses,
                        "meeting_id": st.session_state.get("meeting_id")
                    }
                    eval_resp = httpx.post(
                        f"{API_BASE}{APIEndpoints.EVALUATE}", 
                        json=eval_payload,
                        timeout=Defaults.REQUEST_TIMEOUT
                    )
                    
                    # Step 3: Processing results
                    status_text.text("💾 Processing and saving results...")
                    progress_bar.progress(80)
                    
                    if eval_resp.status_code == 200:
                        # Step 4: Complete
                        status_text.text("✅ Evaluation complete!")
                        progress_bar.progress(100)
                        st.success("✅ Evaluation complete! Refreshing dashboard...")
                        import time
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"❌ Evaluation failed: {eval_resp.status_code}")
                        progress_bar.progress(0)
                        status_text.text("")
                except Exception as e:
                    st.error(f"❌ Evaluation error: {str(e)}")
                    progress_bar.progress(0)
                    status_text.text("")

    st.divider()

    try:
        response = httpx.get(
            f"{API_BASE}{APIEndpoints.METRICS}",
            timeout=Defaults.REQUEST_TIMEOUT
        )
        if response.status_code == 200:
            metrics_data = response.json()
            if not metrics_data:
                st.info("📊 No metrics recorded yet. Start chatting and run an evaluation to see metrics!")
            else:
                df = pd.DataFrame(metrics_data)
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                
                # Sort by timestamp (newest first)
                df = df.sort_values(by='timestamp', ascending=False)
                
                # Top Ranks / KPIs
                st.subheader("📌 Latest Metrics")
                col1, col2, col3, col4 = st.columns(4)
                # After sorting, the first row is the latest
                latest = df.iloc[0]
                col1.metric("Faithfulness", f"{latest['faithfulness']:.3f}")
                col2.metric("Relevancy", f"{latest['answer_relevancy']:.3f}")
                col3.metric("Precision", f"{latest['context_precision']:.3f}")
                col4.metric("Avg Latency", f"{latest['latency_avg_ms']:.0f}ms")

                st.subheader("📈 Trends Over Time")
                # Trends should be chronological
                chart_df = df.sort_values(by='timestamp').set_index('timestamp')[['faithfulness', 'answer_relevancy', 'context_precision']]
                st.line_chart(chart_df)
                
                # Summary table
                st.subheader("📋 Evaluation History")
                # df is already sorted newest first
                display_df = df[['timestamp', 'faithfulness', 'answer_relevancy', 'context_precision', 'average_score', 'latency_avg_ms']].head(10).copy()
                display_df.columns = ['Timestamp', 'Faithfulness', 'Relevancy', 'Precision', 'Avg Score', 'Latency (ms)']
                st.dataframe(display_df, use_container_width=True)
        else:
            st.error(f"❌ Failed to fetch metrics: {response.status_code}")
    except httpx.RequestError as e:
        st.error(f"❌ Connection error: {str(e)}")
    except Exception as e:
        st.error(f"❌ Unexpected error: {str(e)}")

