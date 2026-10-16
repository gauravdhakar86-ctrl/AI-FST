import base64
import hashlib
import hmac
import json
import os
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import requests
import streamlit as st
import streamlit.components.v1 as components
from cryptography.fernet import Fernet
from PIL import Image

# ====== CHANGE THESE TWO ======
APP_NAME = "My Personal GPT"
SYSTEM_PROMPT = (
    "You are my personal assistant. Give clear, direct answers with simple "
    "examples. Reply in the same language the user writes in (English, Hindi or Hinglish)."
)
# ==============================

st.set_page_config(page_title=APP_NAME, page_icon="🤖")

CHAT_DIR = Path(__file__).parent / "chats"
CHAT_DIR.mkdir(exist_ok=True)


def user_dir():
    d = CHAT_DIR / st.session_state.user
    d.mkdir(exist_ok=True)
    return d

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:wght@600;700&family=Instrument+Sans:wght@400;500;600&display=swap');
:root{--bg:#10151F;--surface:#18202E;--line:#263046;--text:#E9EDF5;--muted:#8E9AB3;--accent:#8B9BFF;}
html, body, .stApp{background:var(--bg)!important;color:var(--text);font-family:'Instrument Sans',sans-serif;}
header[data-testid="stHeader"]{background:transparent;}
#MainMenu, footer{visibility:hidden;}
.block-container{max-width:760px;padding-top:2.2rem;padding-bottom:6rem;}
.app-title{font-family:'Bricolage Grotesque',sans-serif;font-size:2.1rem;font-weight:700;letter-spacing:-0.02em;margin:0;color:var(--text);}
.app-sub{color:var(--muted);margin:.2rem 0 1.6rem;font-size:.98rem;}
.hello{font-family:'Bricolage Grotesque',sans-serif;font-size:1.5rem;font-weight:600;margin:2rem 0 1rem;color:var(--text);}
.stApp p, .stApp li, .stApp label, .stApp span, .stMarkdown{color:var(--text);}
[data-testid="stSidebar"]{background:var(--surface)!important;border-right:1px solid var(--line);}
[data-testid="stSidebar"] input{background:var(--bg)!important;color:var(--text)!important;border:1px solid var(--line)!important;}
[data-testid="stChatMessage"]{background:transparent;padding:.35rem 0;}
[data-testid="stChatMessage"] p{line-height:1.7;}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]){background:var(--surface);border:1px solid var(--line);border-radius:16px 16px 4px 16px;padding:.7rem 1rem;}
[data-testid="stChatInput"]{background:var(--surface)!important;border:1px solid var(--line)!important;border-radius:16px!important;}
[data-testid="stChatInput"] textarea{color:var(--text)!important;}
.stButton>button{background:var(--surface);color:var(--text);border:1px solid var(--line);border-radius:12px;text-align:left;padding:.6rem .9rem;font-family:'Instrument Sans',sans-serif;}
.stButton>button:hover{border-color:var(--accent);color:var(--text);}
.stButton>button:focus-visible, textarea:focus-visible, input:focus-visible{outline:2px solid var(--accent)!important;outline-offset:2px;}
pre, code{background:#0B1018!important;border-radius:10px;}
#latest-answer{scroll-margin-top:90px;}
.loader{padding:1.2rem 0 .6rem;}
.loader .emojis span{display:inline-block;font-size:2rem;margin-right:.5rem;animation:hop 1.2s ease-in-out infinite;}
.loader .emojis span:nth-child(2){animation-delay:.15s}
.loader .emojis span:nth-child(3){animation-delay:.3s}
.loader .emojis span:nth-child(4){animation-delay:.45s}
.loader .emojis span:nth-child(5){animation-delay:.6s}
.loader .txt{color:var(--muted);margin-top:.4rem;animation:pulse 1.8s ease-in-out infinite;}
@keyframes hop{0%,100%{transform:translateY(0)}40%{transform:translateY(-14px)}}
@keyframes pulse{0%,100%{opacity:.5}50%{opacity:1}}
@media (prefers-reduced-motion: reduce){.loader .emojis span,.loader .txt{animation:none}}
</style>
""", unsafe_allow_html=True)

st.markdown(
    f'<div class="app-title">{APP_NAME}</div>'
    '<div class="app-sub">Poochho, seedha jawab milega.</div>',
    unsafe_allow_html=True,
)

LOADER_HTML = (
    '<div class="loader"><div class="emojis">'
    '<span>🔍</span><span>📚</span><span>🧠</span><span>✨</span><span>🚀</span></div>'
    '<div class="txt">Research chal rahi hai, thoda ruko...</div></div>'
)


def secret(name):
    try:
        return st.secrets.get(name, "")
    except Exception:
        return ""


# ---------- accounts: password hashed, API keys encrypted with the user's password ----------
DB_PATH = Path(__file__).parent / "users.db"
KEY_NAMES = ("gemini_key", "groq_key", "openrouter_key")


def db():
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, "
                "pw_salt BLOB, pw_hash BLOB, enc_salt BLOB, keys_blob BLOB)")
    return con


def _scrypt(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


def _fkey(password, enc_salt):
    return base64.urlsafe_b64encode(_scrypt(password, enc_salt))


def signup(u, p):
    if not re.fullmatch(r"[A-Za-z0-9_.-]{3,30}", u):
        return "Username 3-30 characters ka rakho (letters, numbers, _ . -)."
    if len(p) < 6:
        return "Password kam se kam 6 characters ka rakho."
    con = db()
    try:
        if con.execute("SELECT 1 FROM users WHERE username=?", (u,)).fetchone():
            return "Ye username pehle se le liya gaya hai."
        pw_salt, enc_salt = os.urandom(16), os.urandom(16)
        blob = Fernet(_fkey(p, enc_salt)).encrypt(b"{}")
        con.execute("INSERT INTO users VALUES (?,?,?,?,?)",
                    (u, pw_salt, _scrypt(p, pw_salt), enc_salt, blob))
        con.commit()
    finally:
        con.close()
    return None


def login(u, p):
    con = db()
    try:
        row = con.execute("SELECT pw_salt, pw_hash, enc_salt, keys_blob FROM users WHERE username=?",
                          (u,)).fetchone()
    finally:
        con.close()
    if not row or not hmac.compare_digest(_scrypt(p, row[0]), row[1]):
        return None
    fkey = _fkey(p, row[2])
    try:
        keys = json.loads(Fernet(fkey).decrypt(row[3]))
    except Exception:
        keys = {}
    return keys, fkey


def start_session(u, keys, fkey):
    st.session_state.user = u
    st.session_state.fkey = fkey
    for k in KEY_NAMES:
        st.session_state[k] = keys.get(k, "")


def save_keys_cb():
    keys = {k: st.session_state.get(k, "").strip() for k in KEY_NAMES}
    blob = Fernet(st.session_state.fkey).encrypt(json.dumps(keys).encode())
    con = db()
    con.execute("UPDATE users SET keys_blob=? WHERE username=?", (blob, st.session_state.user))
    con.commit()
    con.close()
    st.toast("Keys save ho gayi ✅")


def logout_cb():
    for k in list(st.session_state.keys()):
        del st.session_state[k]


if "user" not in st.session_state:
    st.session_state.user = None

if not st.session_state.user:
    tab_in, tab_up = st.tabs(["Login", "Sign up"])
    with tab_in:
        li_u = st.text_input("Username", key="li_u")
        li_p = st.text_input("Password", type="password", key="li_p")
        if st.button("Login", key="li_b"):
            res = login(li_u.strip(), li_p)
            if res is None:
                st.error("Username ya password galat hai.")
            else:
                start_session(li_u.strip(), *res)
                st.rerun()
    with tab_up:
        su_u = st.text_input("Naya username", key="su_u")
        su_p = st.text_input("Naya password", type="password", key="su_p")
        st.caption("Password yaad rakhna: isi se tumhari API keys encrypt hoti hain, "
                   "bhool gaye to keys wapas nahi aa sakti.")
        if st.button("Account banao", key="su_b"):
            err = signup(su_u.strip(), su_p)
            if err:
                st.error(err)
            else:
                start_session(su_u.strip(), {}, _fkey(su_p, db().execute(
                    "SELECT enc_salt FROM users WHERE username=?", (su_u.strip(),)).fetchone()[0]))
                st.rerun()
    st.stop()


# ---------- chat history on disk ----------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "chat_id" not in st.session_state:
    st.session_state.chat_id = None


def list_chats():
    items = []
    for f in sorted(user_dir().glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            items.append((f.stem, json.loads(f.read_text(encoding="utf-8")).get("title", "Chat")))
        except Exception:
            pass
    return items


def save_chat():
    if not st.session_state.messages:
        return
    if not st.session_state.chat_id:
        st.session_state.chat_id = str(int(time.time()))
    first = next((m["content"] for m in st.session_state.messages if m["role"] == "user"), "Chat")
    data = {"title": (first[:40] or "Image chat"), "messages": st.session_state.messages}
    (user_dir() / f"{st.session_state.chat_id}.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8")


def open_chat(cid):
    data = json.loads((user_dir() / f"{cid}.json").read_text(encoding="utf-8"))
    st.session_state.messages = data["messages"]
    st.session_state.chat_id = cid


def new_chat():
    st.session_state.messages = []
    st.session_state.chat_id = None


def delete_chat(cid):
    (user_dir() / f"{cid}.json").unlink(missing_ok=True)
    if st.session_state.chat_id == cid:
        new_chat()


# ---------- sidebar settings ----------
st.sidebar.header("Settings")
gemini_key = st.sidebar.text_input("Gemini key", key="gemini_key", type="password").strip()
groq_key = st.sidebar.text_input("Groq key", key="groq_key", type="password").strip()
openrouter_key = st.sidebar.text_input("OpenRouter key", key="openrouter_key", type="password").strip()
st.sidebar.button("💾 Keys save karo", on_click=save_keys_cb, use_container_width=True)
mode = st.sidebar.radio(
    "Mode", ["Fast", "Best answer"],
    help="Fast = one AI answers (saves free limits). Best answer = several AIs work in the "
         "background and you get one polished answer.")
web = st.sidebar.toggle("🌐 Web search (Gemini)", value=False,
                        help="Gemini searches Google for fresh info. Free limits apply.")

SKIP = ("image", "tts", "live", "audio", "embed", "robotics", "computer", "veo",
        "imagen", "whisper", "guard", "orpheus", "playai", "moderation")
GROQ_VISION = ("llama-4", "scout", "maverick", "vision")


# ---------- model discovery ----------
@st.cache_data(ttl=3600, show_spinner=False)
def gemini_models(key, vision):
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models?pageSize=200",
                     headers={"x-goog-api-key": key}, timeout=30)
    r.raise_for_status()
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    names = [n for n in names if "flash" in n and not any(s in n for s in SKIP)]
    stable = sorted([n for n in names if "preview" not in n and "exp" not in n], reverse=True)
    other = sorted([n for n in names if n not in stable], reverse=True)
    return (stable + other)[:5]


@st.cache_data(ttl=3600, show_spinner=False)
def groq_models(key, vision):
    r = requests.get("https://api.groq.com/openai/v1/models",
                     headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    ids = [m["id"] for m in r.json()["data"] if not any(s in m["id"] for s in SKIP)]
    if vision:
        return [i for i in ids if any(v in i for v in GROQ_VISION)][:4]
    ids.sort(key=lambda i: (0 if "llama" in i or "gpt-oss" in i else 1, i))
    return ids[:5]


@st.cache_data(ttl=3600, show_spinner=False)
def openrouter_models(key, vision):
    r = requests.get("https://openrouter.ai/api/v1/models",
                     headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    data = [m for m in r.json()["data"]
            if m["id"].endswith(":free") and not any(s in m["id"] for s in SKIP)]
    if vision:
        data = [m for m in data if "image" in m.get("architecture", {}).get("input_modalities", [])]
    ids = [m["id"] for m in data]
    pref = ("llama", "gpt-oss", "gemma", "qwen", "deepseek", "mistral")
    ids.sort(key=lambda i: (0 if any(p in i for p in pref) else 1, i))
    return ids[:6]


# ---------- calls: messages = [{"role","content","images":[{"mime","data"}]}] ----------
def call_gemini(model, messages, web_on):
    contents = []
    for m in messages:
        parts = [{"text": m["content"]}]
        for im in m.get("images", []):
            parts.append({"inline_data": {"mime_type": im["mime"], "data": im["data"]}})
        contents.append({"role": "user" if m["role"] == "user" else "model", "parts": parts})
    body = {"contents": contents,
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    hdr = {"x-goog-api-key": gemini_key}
    if web_on:
        body["tools"] = [{"google_search": {}}]
    r = requests.post(url, headers=hdr, json=body, timeout=120)
    if not r.ok and web_on:          # search not allowed for this model/key -> answer without it
        body.pop("tools")
        r = requests.post(url, headers=hdr, json=body, timeout=120)
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)


def call_openai_style(url, key, model, messages):
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in messages:
        if m.get("images"):
            content = [{"type": "text", "text": m["content"]}] + [
                {"type": "image_url", "image_url": {"url": f"data:{im['mime']};base64,{im['data']}"}}
                for im in m["images"]]
        else:
            content = m["content"]
        msgs.append({"role": m["role"], "content": content})
    r = requests.post(url, headers={"Authorization": f"Bearer {key}"},
                      json={"model": model, "messages": msgs}, timeout=120)
    if not r.ok:
        raise RuntimeError(f"{r.status_code}: {r.text[:200]}")
    return r.json()["choices"][0]["message"]["content"]


PROVIDERS = {}
if gemini_key:
    PROVIDERS["Gemini"] = (gemini_models, call_gemini, gemini_key)
if groq_key:
    PROVIDERS["Groq"] = (groq_models,
        lambda m, msgs, w: call_openai_style("https://api.groq.com/openai/v1/chat/completions", groq_key, m, msgs),
        groq_key)
if openrouter_key:
    PROVIDERS["OpenRouter"] = (openrouter_models,
        lambda m, msgs, w: call_openai_style("https://openrouter.ai/api/v1/chat/completions", openrouter_key, m, msgs),
        openrouter_key)


def ask_provider(name, messages, vision, web_on):
    list_fn, call_fn, key = PROVIDERS[name]
    errors = []
    candidates = list_fn(key, vision)
    if not candidates:
        raise RuntimeError(f"{name}: no model available for this request")
    for m in candidates:
        try:
            return call_fn(m, messages, web_on)
        except Exception as e:
            errors.append(f"{m}: {e}")
    raise RuntimeError(f"{name} failed -> " + " | ".join(errors))


def prep(msgs, vision):
    out = []
    for m in msgs:
        text = m["content"]
        if m.get("images") and not vision:
            text += "\n[An image was attached earlier]"
        out.append({"role": m["role"], "content": text,
                    "images": m.get("images", []) if vision else []})
    return out


def get_answer(msgs, vision, web_on):
    messages = prep(msgs, vision)
    names = list(PROVIDERS)
    if mode == "Fast":
        errors = []
        for n in names:
            try:
                return ask_provider(n, messages, vision, web_on)
            except Exception as e:
                errors.append(str(e))
        raise RuntimeError("\n".join(errors))

    def safe(n):
        try:
            return n, ask_provider(n, messages, vision, web_on)
        except Exception:
            return n, None

    with ThreadPoolExecutor() as pool:
        results = [a for _, a in pool.map(safe, names) if a]
    if not results:
        raise RuntimeError("No AI could answer. Check your keys.")
    if len(results) == 1:
        return results[0]
    drafts = "\n\n---\n\n".join(f"Draft {i+1}:\n{a}" for i, a in enumerate(results))
    merge = messages[:-1] + [{"role": "user", "images": [], "content": (
        f"Question: {messages[-1]['content']}\n\nHere are draft answers:\n\n{drafts}\n\n"
        "Write ONE final answer that keeps the most accurate and useful parts. "
        "Do not mention drafts, other AIs, or any comparison. Just give the answer.")}]
    try:
        return ask_provider(names[0], merge, False, False)
    except Exception:
        return results[0]


def process_image(f):
    img = Image.open(f).convert("RGB")
    img.thumbnail((1024, 1024))
    buf = BytesIO()
    img.save(buf, "JPEG", quality=85)
    return {"mime": "image/jpeg", "data": base64.b64encode(buf.getvalue()).decode()}


def show_message(m):
    with st.chat_message(m["role"]):
        for im in m.get("images", []):
            st.image(base64.b64decode(im["data"]), width=240)
        st.markdown(m["content"])


def scroll_to_answer():
    components.html(
        "<script>const el=window.parent.document.getElementById('latest-answer');"
        "if(el){el.scrollIntoView({behavior:'smooth',block:'start'});}</script>",
        height=0)


# ---------- chat UI ----------
for m in st.session_state.messages:
    show_message(m)

SUGGESTIONS = [
    "Subnetting ko examples ke saath samjhao",
    "Python ke important questions batao",
    "Email likhne me madad karo",
    "Aaj ka study plan banao",
]

inp = st.chat_input("Kuch bhi poochho... (📎 se image bhi bhej sakte ho)",
                    accept_file="multiple", file_type=["png", "jpg", "jpeg", "webp"])
prompt, files = None, []
if inp:
    prompt = inp["text"] or ""
    files = inp["files"] or []
    if not prompt and files:
        prompt = "Is image ke baare me batao."

hero = st.empty()
if not st.session_state.messages:
    with hero.container():
        st.markdown('<div class="hello">Aaj kya karna hai?</div>', unsafe_allow_html=True)
        cols = st.columns(2)
        for i, sug in enumerate(SUGGESTIONS):
            if cols[i % 2].button(sug, key=f"sug{i}", use_container_width=True):
                prompt, files = sug, []

if prompt:
    hero.empty()
    if not PROVIDERS:
        st.warning("Sidebar me kam se kam 1 API key daalo.")
        st.stop()
    images = []
    for f in files:
        try:
            images.append(process_image(f))
        except Exception:
            st.warning(f"Image {getattr(f, 'name', '')} padh nahi payi.")
    user_msg = {"role": "user", "content": prompt, "images": images}
    st.session_state.messages.append(user_msg)
    show_message(user_msg)

    with st.chat_message("assistant"):
        st.markdown('<div id="latest-answer"></div>', unsafe_allow_html=True)
        loader = st.empty()
        loader.markdown(LOADER_HTML, unsafe_allow_html=True)
        try:
            answer = get_answer(st.session_state.messages[-10:], bool(images), web)
        except Exception as e:
            answer = f"Error: {e}"
        loader.empty()
        st.markdown(answer)
    st.session_state.messages.append({"role": "assistant", "content": answer})
    save_chat()
    scroll_to_answer()

# ---------- sidebar: history (drawn last so it shows the newest chat) ----------
with st.sidebar:
    st.divider()
    st.caption(f"👤 {st.session_state.user}")
    st.button("Logout", on_click=logout_cb, use_container_width=True)
    st.button("➕ New chat", on_click=new_chat, use_container_width=True)
    st.subheader("💬 History")
    chats = list_chats()
    if not chats:
        st.caption("Abhi koi saved chat nahi hai.")
    for cid, title in chats:
        c1, c2 = st.columns([5, 1])
        label = ("● " if cid == st.session_state.chat_id else "") + title
        c1.button(label, key=f"open{cid}", on_click=open_chat, args=(cid,), use_container_width=True)
        c2.button("🗑", key=f"del{cid}", on_click=delete_chat, args=(cid,))
