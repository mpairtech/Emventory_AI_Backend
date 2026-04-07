import streamlit as st
import requests


API_BASE_URL = "http://127.0.0.1:8000/api/v1/content"
API_KEY      = "d866db0946c3a50a33fc8b985777a9da86433a92bc56c9c09938b3753aba0a60"       
KEY_INPUT    = "org_123"        

# ── Page config ───────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Emventory AI — Content Generator",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ─────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&display=swap');

/* ── Base ── */
html, body, [class*="css"] {
    font-family: 'DM Sans', sans-serif;
    background-color: #0a0a0f;
    color: #e8e6f0;
}

.stApp {
    background: #0a0a0f;
}

/* ── Hide default streamlit chrome ── */
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1100px; }

/* ── Hero header ── */
.hero {
    text-align: center;
    padding: 3rem 1rem 2rem;
    margin-bottom: 1rem;
}
.hero-badge {
    display: inline-block;
    background: linear-gradient(135deg, #7c3aed22, #06b6d422);
    border: 1px solid #7c3aed55;
    color: #a78bfa;
    font-family: 'DM Sans', sans-serif;
    font-size: 0.72rem;
    font-weight: 500;
    letter-spacing: 0.15em;
    text-transform: uppercase;
    padding: 0.35rem 1rem;
    border-radius: 100px;
    margin-bottom: 1.2rem;
}
.hero h1 {
    font-family: 'Syne', sans-serif;
    font-size: clamp(2.2rem, 5vw, 3.8rem);
    font-weight: 800;
    line-height: 1.1;
    background: linear-gradient(135deg, #ffffff 0%, #a78bfa 50%, #38bdf8 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin: 0 0 0.8rem;
}
.hero p {
    font-size: 1.05rem;
    color: #94a3b8;
    font-weight: 300;
    max-width: 520px;
    margin: 0 auto;
    line-height: 1.65;
}

/* ── Section label ── */
.section-label {
    font-family: 'Syne', sans-serif;
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: #7c3aed;
    margin-bottom: 0.6rem;
    margin-top: 1.8rem;
}

/* ── Card ── */
.card {
    background: #13131a;
    border: 1px solid #1e1e2e;
    border-radius: 16px;
    padding: 1.8rem;
    margin-bottom: 1.2rem;
}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stNumberInput > div > div > input,
.stSelectbox > div > div {
    background: #0f0f18 !important;
    border: 1px solid #1e1e2e !important;
    border-radius: 10px !important;
    color: #e8e6f0 !important;
    font-family: 'DM Sans', sans-serif !important;
    font-size: 0.9rem !important;
    transition: border-color 0.2s;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus {
    border-color: #7c3aed !important;
    box-shadow: 0 0 0 3px #7c3aed18 !important;
}
.stTextInput label, .stTextArea label,
.stNumberInput label, .stSelectbox label {
    color: #64748b !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

/* ── Buttons ── */
.stButton > button {
    background: linear-gradient(135deg, #7c3aed, #6d28d9) !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-family: 'Syne', sans-serif !important;
    font-weight: 700 !important;
    font-size: 0.88rem !important;
    letter-spacing: 0.05em;
    padding: 0.65rem 2rem !important;
    transition: all 0.2s !important;
    width: 100%;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #6d28d9, #5b21b6) !important;
    transform: translateY(-1px);
    box-shadow: 0 8px 25px #7c3aed44 !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: #13131a;
    border-radius: 12px;
    padding: 0.3rem;
    border: 1px solid #1e1e2e;
    gap: 0.2rem;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: #64748b !important;
    font-family: 'Syne', sans-serif !important;
    font-weight: 600 !important;
    font-size: 0.82rem !important;
    border-radius: 8px !important;
    padding: 0.5rem 1.2rem !important;
    border: none !important;
}
.stTabs [aria-selected="true"] {
    background: #7c3aed !important;
    color: white !important;
}
.stTabs [data-baseweb="tab-panel"] {
    padding-top: 1.5rem;
}

/* ── Result cards ── */
.result-box {
    background: #0f0f18;
    border: 1px solid #1e1e2e;
    border-radius: 14px;
    padding: 1.6rem;
    margin: 1rem 0;
    line-height: 1.8;
    font-size: 0.92rem;
    color: #cbd5e1;
    white-space: pre-wrap;
}
.result-box-social {
    background: linear-gradient(135deg, #0f0f18, #13111f);
    border: 1px solid #7c3aed33;
    border-radius: 14px;
    padding: 1.6rem;
    margin: 1rem 0;
    line-height: 1.8;
    font-size: 0.95rem;
    color: #e2e8f0;
}

/* ── Bullet item ── */
.bullet-item {
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    padding: 0.65rem 0;
    border-bottom: 1px solid #1e1e2e;
    font-size: 0.9rem;
    color: #cbd5e1;
}
.bullet-item:last-child { border-bottom: none; }
.bullet-dot {
    width: 6px;
    height: 6px;
    background: #7c3aed;
    border-radius: 50%;
    margin-top: 0.45rem;
    flex-shrink: 0;
}

/* ── Hashtag pill ── */
.hashtag-row { display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.8rem; }
.hashtag-pill {
    background: #1e1e2e;
    border: 1px solid #7c3aed44;
    color: #a78bfa;
    font-size: 0.82rem;
    font-weight: 500;
    padding: 0.3rem 0.85rem;
    border-radius: 100px;
    font-family: 'DM Sans', sans-serif;
}

/* ── Metric strip ── */
.metric-strip {
    display: flex;
    gap: 1rem;
    margin: 0.8rem 0 1.2rem;
}
.metric-chip {
    background: #13131a;
    border: 1px solid #1e1e2e;
    border-radius: 8px;
    padding: 0.4rem 0.9rem;
    font-size: 0.78rem;
    color: #64748b;
}
.metric-chip span {
    color: #a78bfa;
    font-weight: 600;
    margin-left: 0.3rem;
}

/* ── Success / error ── */
.stSuccess, .stAlert { border-radius: 10px !important; }

/* ── Divider ── */
hr { border-color: #1e1e2e !important; margin: 1.5rem 0 !important; }

/* ── Expander ── */
.streamlit-expanderHeader {
    background: #13131a !important;
    border: 1px solid #1e1e2e !important;
    border-radius: 10px !important;
    color: #64748b !important;
    font-size: 0.8rem !important;
}
</style>
""", unsafe_allow_html=True)

# ── Hero ───────────────────────────────────────────────────────────────────
st.markdown("""
<div class="hero">
    <div class="hero-badge">✦ Powered by Emventory AI</div>
    <h1>Content Generator</h1>
    <p>Turn your product data into professional ecommerce descriptions and social media posts instantly.</p>
</div>
""", unsafe_allow_html=True)

# ── API call helper ────────────────────────────────────────────────────────
def call_api(endpoint: str, payload: dict) -> tuple[dict | None, int, str]:
    try:
        resp = requests.post(
            f"{API_BASE_URL}/{endpoint}",
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
        return None, 0, "Cannot connect to the server. Please try again shortly."
    except requests.exceptions.Timeout:
        return None, 0, "The request timed out. Please try again."
    except Exception as e:
        return None, 0, str(e)

# ── Product form ───────────────────────────────────────────────────────────
st.markdown('<div class="section-label">Product Information</div>', unsafe_allow_html=True)

with st.container():
    col1, col2, col3 = st.columns([2, 1, 1])
    with col1:
        name = st.text_input("Product Name", placeholder="e.g. Samsung Galaxy S24 Ultra")
    with col2:
        brand = st.text_input("Brand", placeholder="e.g. Samsung")
    with col3:
        category = st.text_input("Category", placeholder="e.g. Smartphone")

    col4, col5 = st.columns([1, 3])
    with col4:
        price = st.number_input("Price (BDT)", min_value=0.0, value=0.0, step=500.0)
    with col5:
        specs_raw = st.text_area(
            "Specifications (one per line)",
            placeholder="6.8-inch QHD+ AMOLED display\nSnapdragon 8 Gen 3\n200MP main camera\n5000mAh battery",
            height=120,
        )

st.markdown('<div class="section-label">Preferences</div>', unsafe_allow_html=True)

col6, col7, col8, col9 = st.columns(4)
with col6:
    language = st.selectbox("Language", ["English", "Bengali (বাংলা)", "Arabic"], index=0)
with col7:
    tone = st.selectbox("Tone", ["Casual", "Formal", "Persuasive"], index=0)
with col8:
    region = st.selectbox("Region", ["BD", "IN", "US", "UK", "AE"], index=0)
with col9:
    query = st.text_input("Search Context", placeholder="e.g. best camera phone")

# Map display language to API language code
lang_map = {"English": "english", "Bengali (বাংলা)": "bn", "Arabic": "ar"}

def build_payload() -> dict | None:
    if not name.strip():
        st.error("Please enter a product name.")
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

# ── Output tabs ────────────────────────────────────────────────────────────
st.markdown("---")
st.markdown('<div class="section-label">Generated Output</div>', unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs(["📄  Product Description", "📱  Social Media Post", "⚡  Generate Both"])

# ── Tab 1: Description ─────────────────────────────────────────────────────
with tab1:
    if st.button("Generate Description", key="gen_desc", type="primary"):
        payload = build_payload()
        if payload:
            with st.spinner("Writing your product description..."):
                data, code, err = call_api("generate", payload)

            if err:
                st.error(err)
            elif code == 200:
                desc    = data.get("description", {})
                bullets = data.get("feature_bullets", [])

                st.markdown("**Description**")
                st.markdown(f'<div class="result-box">{desc.get("content", "")}</div>', unsafe_allow_html=True)

                st.markdown("**Key Features**")
                bullets_html = "".join([
                    f'<div class="bullet-item"><div class="bullet-dot"></div><div>{b}</div></div>'
                    for b in bullets
                ])
                st.markdown(f'<div class="result-box">{bullets_html}</div>', unsafe_allow_html=True)
            else:
                st.error(f"Error {code}: {data.get('detail', data)}")

# ── Tab 2: Social post ─────────────────────────────────────────────────────
with tab2:
    if st.button("Generate Social Post", key="gen_social", type="primary"):
        payload = build_payload()
        if payload:
            with st.spinner("Crafting your social media post..."):
                data, code, err = call_api("social", payload)

            if err:
                st.error(err)
            elif code == 200:
                post     = data.get("post", {})
                body     = post.get("post_body", "")
                hashtags = post.get("hashtags", [])

                st.markdown("**Post Copy**")
                st.markdown(f'<div class="result-box-social">{body}</div>', unsafe_allow_html=True)

                pills = "".join([f'<span class="hashtag-pill">#{h}</span>' for h in hashtags])
                st.markdown(f'<div class="hashtag-row">{pills}</div>', unsafe_allow_html=True)
            else:
                st.error(f"Error {code}: {data.get('detail', data)}")

# ── Tab 3: Both ────────────────────────────────────────────────────────────
with tab3:
    if st.button("Generate Both", key="gen_both", type="primary"):
        payload = build_payload()
        if payload:
            col_l, col_r = st.columns(2)

            with col_l:
                st.markdown("#### Product Description")
                with st.spinner("Writing description..."):
                    data_g, code_g, err_g = call_api("generate", payload)

                if err_g:
                    st.error(err_g)
                elif code_g == 200:
                    desc    = data_g.get("description", {})
                    bullets = data_g.get("feature_bullets", [])
                    st.markdown(f'<div class="result-box">{desc.get("content","")}</div>', unsafe_allow_html=True)
                    bullets_html = "".join([
                        f'<div class="bullet-item"><div class="bullet-dot"></div><div>{b}</div></div>'
                        for b in bullets
                    ])
                    st.markdown("**Key Features**")
                    st.markdown(f'<div class="result-box">{bullets_html}</div>', unsafe_allow_html=True)
                else:
                    st.error(f"Error {code_g}: {data_g.get('detail', data_g)}")

            with col_r:
                st.markdown("#### Social Media Post")
                with st.spinner("Crafting post..."):
                    data_s, code_s, err_s = call_api("social", payload)

                if err_s:
                    st.error(err_s)
                elif code_s == 200:
                    post     = data_s.get("post", {})
                    hashtags = post.get("hashtags", [])
                    st.markdown(f'<div class="result-box-social">{post.get("post_body","")}</div>', unsafe_allow_html=True)
                    pills = "".join([f'<span class="hashtag-pill">#{h}</span>' for h in hashtags])
                    st.markdown(f'<div class="hashtag-row">{pills}</div>', unsafe_allow_html=True)
                else:
                    st.error(f"Error {code_s}: {data_s.get('detail', data_s)}")