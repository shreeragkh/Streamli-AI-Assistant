import os
import time
from dotenv import load_dotenv
import streamlit as st
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError

# Load environment variables
load_dotenv()

# --- SDK ImportS ---
# We need the main project client
from azure.ai.projects import AIProjectClient
# We still need MessageRole from the agents package
from azure.ai.agents.models import MessageRole

# ------------------ CONFIG -------------------
PROJECT_ENDPOINT = os.getenv("PROJECT_ENDPOINT")
AGENT_ID = os.getenv("AGENT_ID")

if not PROJECT_ENDPOINT:
    PROJECT_ENDPOINT = st.secrets.get("PROJECT_ENDPOINT", "")
if not AGENT_ID:
    AGENT_ID = st.secrets.get("AGENT_ID", "")

# --- Auth and Client ---
# Create ONE client for the entire project
credential = DefaultAzureCredential()
project_client = AIProjectClient(PROJECT_ENDPOINT, credential)

# --------------- STREAMLIT UI ----------------
st.set_page_config(page_title="Foundry Agent Chat", page_icon="🤖", layout="centered")
st.title("🤖 Azure AI Foundry — Text Agent")
st.caption("Simple Streamlit chat that calls a hosted Agent (Thread → Message → Run).")

# Validate config early
if not PROJECT_ENDPOINT or not AGENT_ID:
    st.error("Missing PROJECT_ENDPOINT or AGENT_ID. Set them via env vars or in .streamlit/secrets.toml")
    st.stop()

# Initialize session state
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "history" not in st.session_state:
    st.session_state.history = []

# --- Utilities ---
def ensure_thread():
    """Create (once) and cache a thread for this browser session."""
    if st.session_state.thread_id is None:
        # Access 'threads' through the main client's 'agents' property
        t = project_client.agents.threads.create()
        st.session_state.thread_id = t.id

def ask_agent(user_text: str) -> str:
    """Send a user message, run the agent, and return the assistant reply text."""
    ensure_thread()
    thread_id = st.session_state.thread_id

    # Access 'messages' through the main client
    project_client.agents.messages.create(
    thread_id,
    body={"role": MessageRole.USER, "content": user_text}
)

    # Access 'runs' through the main client
    run = project_client.agents.runs.create(
        thread_id=thread_id, agent_id=AGENT_ID
    )

    # Poll until completion
    with st.status("Thinking…", expanded=False) as status:
        while run.status in ("queued", "in_progress"):
            time.sleep(0.8)
            # Access 'runs' to get the status
            run = project_client.agents.runs.get(thread_id, run.id)
            status.update(label=f"Status: {run.status}")

        if run.status != "completed":
            raise RuntimeError(f"Run ended with status: {run.status}")

    # Access 'messages' to list them
    page = project_client.agents.messages.list(thread_id, order="desc")
    assistant_msg = next((m for m in page if m.role == "assistant"), None)

    if not assistant_msg or not assistant_msg.content:
        return "(No reply content)"

    # Concatenate all text parts
    parts = []
    for c in assistant_msg.content:
        if c.type == "text":
            parts.append(c.text.value)
    return "\n".join(parts).strip() or "(Empty reply)"

# --- Chat history render ---
for who, text in st.session_state.history:
    with st.chat_message(who):
        st.markdown(text)

# --- Input box ---
prompt = st.chat_input("Type your question…")

if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)
    st.session_state.history.append(("user", prompt))

    try:
        with st.chat_message("assistant"):
            with st.spinner("Calling Foundry Agent…"):
                reply = ask_agent(prompt)
                st.markdown(reply)
        st.session_state.history.append(("assistant", reply))

    except ClientAuthenticationError as e:
        st.error("Authentication failed. Make sure you're signed in with `az login` or have valid credentials.")
        st.exception(e)
    except HttpResponseError as e:
        st.error("The service returned an error.")
        st.exception(e)
    except Exception as e:
        st.error("Something went wrong.")
        st.exception(e)

# --- Sidebar info ---
with st.sidebar:
    st.subheader("Session")
    st.write("Thread ID:", st.session_state.thread_id or "—")
    if st.button("🔁 New thread (reset)"):
        st.session_state.thread_id = None
        st.session_state.history = []
        st.rerun()
    st.divider()
    st.caption("Uses Entra ID via DefaultAzureCredential. Ensure your identity has access to the Foundry project and agent.")