# My Personal GPT

A multi-provider AI chat assistant built with Streamlit, featuring user authentication, encrypted API key storage, chat history management, and multi-model consensus responses.

---

## Features

- **Multi-Provider Support**: Integrates with Google Gemini, Groq, and OpenRouter APIs.
- **Dual Response Modes**:
  - **Fast**: Queries providers sequentially until a response is received (saves quota).
  - **Best Answer**: Queries available providers in parallel using multi-threading and synthesizes a consolidated, polished answer.
- **Vision Support**: Upload and analyze multiple images (`PNG`, `JPG`, `JPEG`, `WEBP`).
- **Web Search**: Real-time Google Search integration via supported Gemini models.
- **Secure Authentication**:
  - Passwords hashed using `scrypt`.
  - API keys stored in SQLite, encrypted with Fernet keys derived from the user's password.
- **Persistent Chat History**: Saves chat sessions per user in local JSON format.
- **Dynamic Model Discovery**: Fetches and caches supported models dynamically for each provider.

---

## Project Structure

```text
.
├── app.py              # Main Streamlit application
├── requirements.txt    # Python dependencies
├── users.db            # SQLite database for credentials and encrypted keys
├── chats/              # Directory for per-user chat history JSONs
└── README.md           # Documentation