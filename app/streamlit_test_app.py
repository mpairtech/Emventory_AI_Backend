import streamlit as st
import requests

CONTENT_API_URL = "http://127.0.0.1:8000/api/v1/content"
SEARCH_API_URL  = "http://127.0.0.1:8000/api/v1/search"
API_KEY         = "d866db0946c3a50a33fc8b985777a9da86433a92bc56c9c09938b3753aba0a60"
KEY_INPUT       = "org_123"

# Keep old name as alias so existing call_api() calls still work
API_BASE_URL = CONTENT_API_URL

st.set_page_config(
    page_title="Emventory AI",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
    background: #f7f6f3;
    color: #1a1a1a;
}

.stApp { background: #f7f6f3; }

#MainMenu, footer, header { visibility: hidden; }
.block-container {
    padding: 2.5rem 2rem 4rem;
    max-width: 960px;
}

/* ── Header ── */
.app-header {
    display: flex;
    align-items: baseline;
    gap: 0.6rem;
    padding-bottom: 2rem;
    border-bottom: 1.5px solid #e0ddd6;
    margin-bottom: 2.5rem;
}
.app-logo {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.78rem;
    font-weight: 500;
    color: #888;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.app-title {
    font-size: 1.35rem;
    font-weight: 600;
    color: #1a1a1a;
    letter-spacing: -0.02em;
}
.app-desc {
    margin-left: auto;
    font-size: 0.82rem;
    color: #888;
    font-weight: 400;
}

/* ── Section headings ── */
.sec-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.68rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #aaa;
    margin-bottom: 0.9rem;
    margin-top: 2rem;
}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stNumberInput > div > div > input {
    background: #fff !important;
    border: 1.5px solid #e0ddd6 !important;
    border-radius: 6px !important;
    color: #1a1a1a !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-size: 0.88rem !important;
    transition: border-color 0.15s ease;
    padding: 0.55rem 0.8rem !important;
    box-shadow: none !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #1a1a1a !important;
    box-shadow: none !important;
    outline: none;
}
.stTextInput label, .stTextArea label,
.stNumberInput label, .stSelectbox label {
    font-family: 'IBM Plex Mono', monospace !important;
    color: #888 !important;
    font-size: 0.7rem !important;
    font-weight: 400 !important;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}

/* Selectbox */
.stSelectbox > div > div {
    background: #fff !important;
    border: 1.5px solid #e0ddd6 !important;
    border-radius: 6px !important;
    color: #1a1a1a !important;
    font-family: 'IBM Plex Sans', sans-serif !important;
    font-size: 0.88rem !important;
}
.stSelectbox > div > div:focus-within {
    border-color: #1a1a1a !important;
    box-shadow: none !important;
}

/* ── Button ── */
.stButton > button {
    background: #1a1a1a !important;
    color: #f7f6f3 !important;
    border: none !important;
    border-radius: 6px !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-weight: 500 !important;
    font-size: 0.78rem !important;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    padding: 0.65rem 1.6rem !important;
    width: 100%;
    transition: background 0.15s ease, transform 0.1s ease;
}
.stButton > button:hover {
    background: #333 !important;
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(0,0,0,0.12) !important;
}
.stButton > button:active {
    transform: translateY(0);
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: transparent;
    border-bottom: 1.5px solid #e0ddd6;
    border-radius: 0;
    padding: 0;
    gap: 0;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: #aaa !important;
    font-family: 'IBM Plex Mono', monospace !important;
    font-weight: 400 !important;
    font-size: 0.75rem !important;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    border-radius: 0 !important;
    border: none !important;
    border-bottom: 2px solid transparent !important;
    padding: 0.6rem 1.2rem !important;
    margin-bottom: -1.5px;
}
.stTabs [aria-selected="true"] {
    color: #1a1a1a !important;
    border-bottom: 2px solid #1a1a1a !important;
    background: transparent !important;
}
.stTabs [data-baseweb="tab-panel"] {
    padding-top: 1.8rem;
}

/* ── Results ── */
.result-block {
    background: #fff;
    border: 1.5px solid #e0ddd6;
    border-radius: 8px;
    padding: 1.4rem 1.6rem;
    margin: 1rem 0;
    font-size: 0.88rem;
    line-height: 1.75;
    color: #333;
    white-space: pre-wrap;
}
.result-label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #bbb;
    margin-bottom: 0.6rem;
}
.bullet-row {
    display: flex;
    gap: 0.75rem;
    padding: 0.55rem 0;
    border-bottom: 1px solid #f0ede8;
    font-size: 0.87rem;
    color: #444;
    align-items: flex-start;
}
.bullet-row:last-child { border-bottom: none; }
.bullet-mark {
    font-family: 'IBM Plex Mono', monospace;
    color: #ccc;
    font-size: 0.75rem;
    margin-top: 0.22rem;
    flex-shrink: 0;
}

/* Hashtags */
.tag-row { display: flex; flex-wrap: wrap; gap: 0.45rem; margin-top: 1rem; }
.tag {
    background: #f0ede8;
    color: #666;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.75rem;
    padding: 0.28rem 0.7rem;
    border-radius: 4px;
    border: 1px solid #e0ddd6;
}

/* Divider */
hr { border-color: #e0ddd6 !important; margin: 2rem 0 !important; }

/* Alert / success */
.stAlert { border-radius: 6px !important; font-size: 0.85rem !important; }

/* Spinner */
.stSpinner > div { color: #888 !important; }

/* ── RAG answer ── */
.rag-answer {
    background: #fff;
    border: 1.5px solid #e0ddd6;
    border-radius: 8px;
    padding: 1.4rem 1.6rem;
    margin: 1rem 0 1.6rem;
    font-size: 0.9rem;
    line-height: 1.8;
    color: #222;
}

/* ── Source card ── */
.source-card {
    background: #fff;
    border: 1.5px solid #e0ddd6;
    border-radius: 8px;
    padding: 1rem 1.2rem;
    margin-bottom: 0.6rem;
    display: flex;
    gap: 1rem;
    align-items: flex-start;
}
.source-score {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.72rem;
    color: #aaa;
    background: #f7f6f3;
    border: 1px solid #e0ddd6;
    border-radius: 4px;
    padding: 0.2rem 0.5rem;
    white-space: nowrap;
    margin-top: 0.1rem;
    flex-shrink: 0;
}
.source-body { flex: 1; min-width: 0; }
.source-name {
    font-size: 0.88rem;
    font-weight: 600;
    color: #1a1a1a;
    margin-bottom: 0.25rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.source-meta {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.7rem;
    color: #aaa;
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
}
.source-meta span { white-space: nowrap; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="app-header">
    <span class="app-logo">⬡ Emventory</span>
    <span class="app-title">AI Tools</span>
    <span class="app-desc">RAG Search · Content · Social</span>
</div>
""", unsafe_allow_html=True)

# ── API helper ─────────────────────────────────────────────────────────────
def call_api(endpoint: str, payload: dict) -> tuple[dict | None, int, str]:
    try:
        resp = requests.post(
            f"{CONTENT_API_URL}/{endpoint}",
            json=payload,
            headers={
                "X-API-Key":    API_KEY,
                "X-Key-Input":  KEY_INPUT,
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        return data, resp.status_code, ""
    except requests.exceptions.ConnectionError:
        return None, 0, "Can't reach the server — is it running?"
    except requests.exceptions.Timeout:
        return None, 0, "Request timed out. Try again."
    except Exception as e:
        return None, 0, str(e)


def call_search_api(endpoint: str, payload: dict, params: dict | None = None) -> tuple[dict | None, int, str]:
    try:
        resp = requests.post(
            f"{SEARCH_API_URL}/{endpoint}",
            json=payload,
            params=params,
            headers={
                "X-API-Key":    API_KEY,
                "X-Key-Input":  KEY_INPUT,
                "Content-Type": "application/json",
            },
            timeout=45,
        )
        try:
            data = resp.json()
        except Exception:
            data = {"raw": resp.text}
        return data, resp.status_code, ""
    except requests.exceptions.ConnectionError:
        return None, 0, "Can't reach the server — is it running?"
    except requests.exceptions.Timeout:
        return None, 0, "Request timed out (RAG can take a moment). Try again."
    except Exception as e:
        return None, 0, str(e)

# ── Form ──────────────────────────────────────────────────────────────────
st.markdown('<div class="sec-label">Product</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([3, 1.5, 1.5])
with col1:
    name = st.text_input("Name")
with col2:
    brand = st.text_input("Brand")
with col3:
    category = st.text_input("Category")

col4, col5 = st.columns([1, 3])
with col4:
    price = st.number_input("Price (BDT)", min_value=0.0, value=0.0, step=500.0)
with col5:
    specs_raw = st.text_area("Specifications ", height=110)

st.markdown('<div class="sec-label">Options</div>', unsafe_allow_html=True)

col6, col7, col8, col9 = st.columns(4)
with col6:
    language = st.selectbox("Language", ["English", "Bengali (বাংলা)", "Arabic"])
with col7:
    tone = st.selectbox("Tone", ["Casual", "Formal", "Persuasive"])
with col8:
    region = st.selectbox("Region", ["BD", "IN", "US", "UK", "AE"])
with col9:
    query = st.text_input("Search Context")

lang_map = {"English": "english", "Bengali (বাংলা)": "bn", "Arabic": "ar"}

def build_payload() -> dict | None:
    if not name.strip():
        st.error("Product name is required.")
        return None
    specs = [s.strip() for s in specs_raw.splitlines() if s.strip()]
    payload = {
        "product_data": {
            "name":           name.strip(),
            "category":       category.strip() or None,
            "brand":          brand.strip() or None,
            "specifications": specs,
            "price":          price if price > 0 else None,
        },
        "region":   region,
        "language": lang_map.get(language, "english"),
        "tone":     tone.lower(),
    }
    if query.strip():
        payload["query"] = query.strip()
    return payload

# ── Tabs ──────────────────────────────────────────────────────────────────
st.markdown("---")
tab1, tab2, tab3 = st.tabs(["Description", "Social Post", "Both"])

# ── Tab 1 ─────────────────────────────────────────────────────────────────
with tab1:
    if st.button("Generate description", key="gen_desc"):
        payload = build_payload()
        if payload:
            with st.spinner("Generating…"):
                data, code, err = call_api("generate", payload)

            if err:
                st.error(err)
            elif code == 200:
                desc    = data.get("description", {})
                bullets = data.get("feature_bullets", [])

                st.markdown('<div class="result-label">Description</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="result-block">{desc.get("content", "")}</div>', unsafe_allow_html=True)

                st.markdown('<div class="result-label">Key Features</div>', unsafe_allow_html=True)
                rows = "".join([
                    f'<div class="bullet-row"><span class="bullet-mark">—</span><span>{b}</span></div>'
                    for b in bullets
                ])
                st.markdown(f'<div class="result-block">{rows}</div>', unsafe_allow_html=True)
            else:
                st.error(f"Error {code}: {data.get('detail', data)}")

# ── Tab 2 ─────────────────────────────────────────────────────────────────
with tab2:
    if st.button("Generate post", key="gen_social"):
        payload = build_payload()
        if payload:
            with st.spinner("Generating…"):
                data, code, err = call_api("social", payload)

            if err:
                st.error(err)
            elif code == 200:
                post     = data.get("post", {})
                body     = post.get("post_body", "")
                hashtags = post.get("hashtags", [])

                st.markdown('<div class="result-label">Post</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="result-block">{body}</div>', unsafe_allow_html=True)

                pills = "".join([f'<span class="tag">#{h}</span>' for h in hashtags])
                st.markdown(f'<div class="tag-row">{pills}</div>', unsafe_allow_html=True)
            else:
                st.error(f"Error {code}: {data.get('detail', data)}")

# ── Tab 3 ─────────────────────────────────────────────────────────────────
with tab3:
    if st.button("Generate both", key="gen_both"):
        payload = build_payload()
        if payload:
            col_l, col_r = st.columns(2)

            with col_l:
                st.markdown("**Description**")
                with st.spinner("Generating…"):
                    data_g, code_g, err_g = call_api("generate", payload)

                if err_g:
                    st.error(err_g)
                elif code_g == 200:
                    desc    = data_g.get("description", {})
                    bullets = data_g.get("feature_bullets", [])
                    st.markdown(f'<div class="result-block">{desc.get("content","")}</div>', unsafe_allow_html=True)
                    rows = "".join([
                        f'<div class="bullet-row"><span class="bullet-mark">—</span><span>{b}</span></div>'
                        for b in bullets
                    ])
                    st.markdown('<div class="result-label" style="margin-top:1rem">Features</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="result-block">{rows}</div>', unsafe_allow_html=True)
                else:
                    st.error(f"Error {code_g}: {data_g.get('detail', data_g)}")

            with col_r:
                st.markdown("**Social Post**")
                with st.spinner("Generating…"):
                    data_s, code_s, err_s = call_api("social", payload)

                if err_s:
                    st.error(err_s)
                elif code_s == 200:
                    post     = data_s.get("post", {})
                    hashtags = post.get("hashtags", [])
                    st.markdown(f'<div class="result-block">{post.get("post_body","")}</div>', unsafe_allow_html=True)
                    pills = "".join([f'<span class="tag">#{h}</span>' for h in hashtags])
                    st.markdown(f'<div class="tag-row">{pills}</div>', unsafe_allow_html=True)
                else:
                    st.error(f"Error {code_s}: {data_s.get('detail', data_s)}")


# ══════════════════════════════════════════════════════════════════════════
# RAG SEARCH
# ══════════════════════════════════════════════════════════════════════════

st.markdown("---")
st.markdown('<div class="sec-label">RAG Search</div>', unsafe_allow_html=True)

rag_query = st.text_input("Query", key="rag_query", label_visibility="collapsed",
                           placeholder="Ask anything — e.g. suggest me a budget laptop within 800 dollar")

if st.button("Search", key="rag_search"):
    if not rag_query.strip():
        st.error("Please enter a query.")
    else:
        payload = {
            "query":  rag_query.strip(),
            "org_id": KEY_INPUT,
            "top_k":  5,
        }

        with st.spinner("Searching…"):
            data, code, err = call_search_api("rag", payload)

        if err:
            st.error(err)
        elif code == 200:
            answer  = data.get("answer", "")
            sources = data.get("sources", [])

            st.markdown('<div class="result-label">Answer</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="rag-answer">{answer}</div>', unsafe_allow_html=True)

            if sources:
                st.markdown(
                    f'<div class="result-label">Sources &nbsp;<span style="color:#ccc;font-size:0.6rem">({len(sources)})</span></div>',
                    unsafe_allow_html=True,
                )
                for src in sources:
                    score    = src.get("similarity_score", 0)
                    name_s   = src.get("name", "—")
                    brand_s  = src.get("brand") or ""
                    cat_s    = src.get("category") or ""
                    price_s  = src.get("price")
                    rating_s = src.get("rating")
                    status_s = src.get("status") or ""

                    meta_parts = []
                    if brand_s:
                        meta_parts.append(f"<span>{brand_s}</span>")
                    if cat_s:
                        meta_parts.append(f"<span>{cat_s}</span>")
                    if price_s is not None:
                        meta_parts.append(f"<span>${price_s:,.0f}</span>")
                    if rating_s is not None:
                        meta_parts.append(f"<span>★ {rating_s}</span>")
                    if status_s:
                        meta_parts.append(f"<span>{status_s}</span>")

                    st.markdown(f"""
                    <div class="source-card">
                        <span class="source-score">{score:.2f}</span>
                        <div class="source-body">
                            <div class="source-name">{name_s}</div>
                            <div class="source-meta">{"".join(meta_parts)}</div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.error(f"Error {code}: {data.get('detail', data)}")