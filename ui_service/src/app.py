"""
Streamlit UI for Meeting Intelligence System.
Provides transcript upload and RAG query interface.
"""

import streamlit as st
import httpx
from typing import Optional, Dict, Any

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
                st.success(f"✅ Indexed: {meeting_id}")
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

# Display session state if meeting indexed
if st.session_state.get("meeting_id"):
    st.sidebar.success(f"📌 Session: {st.session_state['meeting_id'][:8]}...")

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
                
                # Display sources if available
                sources = result.get("sources", [])
                if sources:
                    with st.expander("📚 Sources"):
                        for source in set(sources):
                            st.write(f"• {source}")
