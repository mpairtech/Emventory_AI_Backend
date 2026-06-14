ffimport streamlit as st
import requests

CONTENT_API_URL = "http://127.0.0.1:5000/api/v1/content"
SEARCH_API_URL  = "http://127.0.0.1:5000/api/v1/search"
VOICE_API_URL   = "http://127.0.0.1:5000/api/v1/voice"
API_KEY         = "d866db0946c3a50a33fc8b985777a9da86433a92bc56c9c09938b3753aba0a60"
KEY_INPUT       = "org_123"

st.set_page_config(
    page_title="Emventory AI",
    page_icon="✦",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sora:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500&display=swap');

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

html, body, [class*="css"] {
    font-family: 'Sora', sans-serif;
    background: #fafaf8;
    color: #18181b;
}

.stApp { background: #fafaf8; }
#MainMenu, footer, header { visibility: hidden; }

.block-container {
    padding: 3rem 2.5rem 5rem;
    max-width: 900px;
}

/* ── Header ── */
.site-header {
    margin-bottom: 3rem;
}
.site-header-top {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    margin-bottom: 0.4rem;
}
.site-icon {
    width: 34px;
    height: 34px;
    background: #18181b;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 0.9rem;
    color: #fafaf8;
    flex-shrink: 0;
}
.site-name {
    font-size: 1.25rem;
    font-weight: 600;
    letter-spacing: -0.03em;
    color: #18181b;
}
.site-tagline {
    font-size: 0.85rem;
    color: #a0a0a0;
    font-weight: 300;
    margin-left: 0.1rem;
    letter-spacing: 0.01em;
}
.header-divider {
    width: 100%;
    height: 1px;
    background: linear-gradient(to right, #e4e4e0 60%, transparent);
    margin-top: 1.4rem;
}

/* ── Section labels ── */
.sec-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.65rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: #b4b4b0;
    margin-bottom: 1rem;
    margin-top: 0.2rem;
    display: flex;
    align-items: center;
    gap: 0.6rem;
}
.sec-label::after {
    content: '';
    flex: 1;
    height: 1px;
    background: #ebebea;
}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stTextArea > div > div > textarea,
.stNumberInput > div > div > input {
    background: #fff !important;
    border: 1.5px solid #e8e8e4 !important;
    border-radius: 10px !important;
    color: #18181b !important;
    font-family: 'Sora', sans-serif !important;
    font-size: 0.875rem !important;
    padding: 0.6rem 0.9rem !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
    transition: border-color 0.18s, box-shadow 0.18s !important;
}
.stTextInput > div > div > input:focus,
.stTextArea > div > div > textarea:focus,
.stNumberInput > div > div > input:focus {
    border-color: #18181b !important;
    box-shadow: 0 0 0 3px rgba(24,24,27,0.06) !important;
    outline: none !important;
}
.stTextInput label, .stTextArea label,
.stNumberInput label, .stSelectbox label {
    font-family: 'Sora', sans-serif !important;
    color: #7c7c7a !important;
    font-size: 0.78rem !important;
    font-weight: 500 !important;
    letter-spacing: 0.01em !important;
    margin-bottom: 0.3rem !important;
}

/* Selectbox */
.stSelectbox > div > div {
    background: #fff !important;
    border: 1.5px solid #e8e8e4 !important;
    border-radius: 10px !important;
    font-family: 'Sora', sans-serif !important;
    font-size: 0.875rem !important;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04) !important;
}
.stSelectbox > div > div:focus-within {
    border-color: #18181b !important;
    box-shadow: 0 0 0 3px rgba(24,24,27,0.06) !important;
}

/* ── Buttons ── */
.stButton > button {
    background: #18181b !important;
    color: #fafaf8 !important;
    border: none !important;
    border-radius: 10px !important;
    font-family: 'Sora', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    letter-spacing: 0.01em;
    padding: 0.65rem 1.6rem !important;
    width: 100%;
    box-shadow: 0 1px 3px rgba(0,0,0,0.15), 0 1px 2px rgba(0,0,0,0.1) !important;
    transition: all 0.18s ease !important;
}
.stButton > button:hover {
    background: #2d2d30 !important;
    transform: translateY(-1px) !important;
    box-shadow: 0 4px 14px rgba(0,0,0,0.16) !important;
}
.stButton > button:active {
    transform: translateY(0) !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.12) !important;
}

/* ── Tabs ── */
.stTabs [data-baseweb="tab-list"] {
    background: #f0f0ec;
    border: 1.5px solid #e8e8e4;
    border-radius: 12px;
    padding: 4px;
    gap: 2px;
}
.stTabs [data-baseweb="tab"] {
    background: transparent !important;
    color: #9090a0 !important;
    font-family: 'Sora', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.8rem !important;
    letter-spacing: 0.01em;
    border-radius: 8px !important;
    border: none !important;
    padding: 0.45rem 1.1rem !important;
    transition: all 0.15s ease !important;
}
.stTabs [aria-selected="true"] {
    color: #18181b !important;
    background: #fff !important;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1) !important;
}
.stTabs [data-baseweb="tab-panel"] {
    padding-top: 1.6rem;
}

/* ── Result blocks ── */
.result-wrap {
    margin: 1.2rem 0;
}
.result-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.63rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: #c0c0bc;
    margin-bottom: 0.5rem;
}
.result-block {
    background: #fff;
    border: 1.5px solid #e8e8e4;
    border-radius: 12px;
    padding: 1.3rem 1.5rem;
    font-size: 0.875rem;
    line-height: 1.8;
    color: #3a3a3c;
    white-space: pre-wrap;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
}

/* Feature bullets */
.bullet-list {
    background: #fff;
    border: 1.5px solid #e8e8e4;
    border-radius: 12px;
    padding: 0.4rem 0;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    overflow: hidden;
}
.bullet-row {
    display: flex;
    align-items: flex-start;
    gap: 0.8rem;
    padding: 0.6rem 1.4rem;
    font-size: 0.875rem;
    color: #3a3a3c;
    line-height: 1.6;
    border-bottom: 1px solid #f4f4f2;
    transition: background 0.1s;
}
.bullet-row:last-child { border-bottom: none; }
.bullet-row:hover { background: #fafaf8; }
.bullet-dot {
    width: 5px;
    height: 5px;
    background: #d4d4d0;
    border-radius: 50%;
    margin-top: 0.5rem;
    flex-shrink: 0;
}

/* Hashtags */
.tag-row { display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.9rem; }
.tag {
    background: #f0f0ec;
    color: #606060;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    padding: 0.28rem 0.65rem;
    border-radius: 6px;
    border: 1px solid #e4e4e0;
    transition: background 0.15s;
}
.tag:hover { background: #e8e8e4; }

/* Divider */
.section-gap {
    height: 1px;
    background: linear-gradient(to right, transparent, #e4e4e0 20%, #e4e4e0 80%, transparent);
    margin: 2.5rem 0;
}

/* ── RAG answer ── */
.rag-answer {
    background: #fff;
    border: 1.5px solid #e8e8e4;
    border-radius: 12px;
    padding: 1.4rem 1.6rem;
    font-size: 0.9rem;
    line-height: 1.85;
    color: #2a2a2c;
    box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    position: relative;
}
.rag-answer::before {
    content: '✦';
    position: absolute;
    top: -0.55rem;
    left: 1.2rem;
    background: #fafaf8;
    padding: 0 0.35rem;
    font-size: 0.65rem;
    color: #c8c8c4;
}

/* ── Source cards ── */
.source-card {
    background: #fff;
    border: 1.5px solid #e8e8e4;
    border-radius: 10px;
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.5rem;
    display: flex;
    gap: 0.9rem;
    align-items: flex-start;
    box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    transition: border-color 0.15s, box-shadow 0.15s;
}
.source-card:hover {
    border-color: #d0d0cc;
    box-shadow: 0 2px 8px rgba(0,0,0,0.07);
}
.source-score {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem;
    color: #b0b0ac;
    background: #f4f4f2;
    border: 1px solid #e8e8e4;
    border-radius: 6px;
    padding: 0.18rem 0.45rem;
    white-space: nowrap;
    margin-top: 0.12rem;
    flex-shrink: 0;
}
.source-body { flex: 1; min-width: 0; }
.source-name {
    font-size: 0.875rem;
    font-weight: 600;
    color: #18181b;
    margin-bottom: 0.25rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.source-meta {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.68rem;
    color: #b0b0ac;
    display: flex;
    flex-wrap: wrap;
    gap: 0.6rem;
}

/* ── Transcript pill ── */
.transcript-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.6rem;
    background: #f4f4f2;
    border: 1.5px solid #e8e8e4;
    border-radius: 50px;
    padding: 0.5rem 1.1rem;
    margin-bottom: 1.2rem;
    font-size: 0.875rem;
    color: #3a3a3c;
    line-height: 1.5;
}
.t-label {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.6rem;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #b4b4b0;
    flex-shrink: 0;
    background: #fff;
    padding: 0.15rem 0.5rem;
    border-radius: 50px;
    border: 1px solid #e4e4e0;
}

/* Empty state hint */
.hint-text {
    font-size: 0.8rem;
    color: #c0c0bc;
    font-style: italic;
    margin-top: 0.5rem;
}

/* Alert styling */
.stAlert { border-radius: 10px !important; font-size: 0.85rem !important; }

/* Spinner */
.stSpinner > div { color: #a0a0a0 !important; }
</style>
""", unsafe_allow_html=True)

# ── Header ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="site-header">
    <div class="site-header-top">
        <div class="site-icon">✦</div>
        <span class="site-name">Emventory AI</span>
    </div>
    <div class="site-tagline">RAG Search · Product Descriptions · Social Posts · Voice</div>
    <div class="header-divider"></div>
</div>
""", unsafe_allow_html=True)


# ── API helpers ────────────────────────────────────────────────────────────
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
            timeout=60,
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


def render_sources(sources: list) -> None:
    if not sources:
        return
    st.markdown(
        f'<div class="result-label" style="margin-top:1.4rem">Sources &nbsp;({len(sources)})</div>',
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
        if brand_s:   meta_parts.append(f"<span>{brand_s}</span>")
        if cat_s:     meta_parts.append(f"<span>{cat_s}</span>")
        if price_s is not None: meta_parts.append(f"<span>৳{price_s:,.0f}</span>")
        if rating_s is not None: meta_parts.append(f"<span>★ {rating_s}</span>")
        if status_s:  meta_parts.append(f"<span>{status_s}</span>")

        st.markdown(f"""
        <div class="source-card">
            <span class="source-score">{score:.2f}</span>
            <div class="source-body">
                <div class="source-name">{name_s}</div>
                <div class="source-meta">{"".join(meta_parts)}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# PRODUCT FORM
# ══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="sec-label">Product details</div>', unsafe_allow_html=True)

col1, col2, col3 = st.columns([3, 1.5, 1.5])
with col1:
    name = st.text_input("Product name", placeholder="e.g. Samsung Galaxy S24 Ultra")
with col2:
    brand = st.text_input("Brand", placeholder="e.g. Samsung")
with col3:
    category = st.text_input("Category", placeholder="e.g. Smartphone")

col4, col5 = st.columns([1, 3])
with col4:
    price = st.number_input("Price (BDT)", min_value=0.0, value=0.0, step=500.0)
with col5:
    specs_raw = st.text_area(
        "Specifications",
        height=110,
        placeholder="One per line — e.g.\n6.8\" Dynamic AMOLED display\n200MP main camera\n5000mAh battery"
    )

st.markdown('<div class="sec-label" style="margin-top:1.8rem">Options</div>', unsafe_allow_html=True)

col6, col7, col8, col9 = st.columns(4)
with col6:
    language = st.selectbox("Language", ["English", "Bengali (বাংলা)", "Arabic"])
with col7:
    tone = st.selectbox("Tone", ["Casual", "Formal", "Persuasive"])
with col8:
    region = st.selectbox("Region", ["BD", "IN", "US", "UK", "AE"])
with col9:
    query = st.text_input("Search context", placeholder="optional keyword")

# ── Social post extras ─────────────────────────────────────────────────────
st.markdown('<div class="sec-label" style="margin-top:1.4rem">Social post extras</div>', unsafe_allow_html=True)

col_price, col_addr = st.columns([1, 3])
with col_price:
    social_price = st.text_input(
        "Display price",
        placeholder="e.g. ৳2,850",
        help="Shown in the post as-is. Leave blank to omit.",
    )
with col_addr:
    shop_address = st.text_input(
        "Shop address",
        placeholder="e.g. 12 Agrabad C/A, Chattogram",
        help="Appended to the post CTA. Leave blank to omit.",
    )

lang_map = {"English": "english", "Bengali (বাংলা)": "Bengali", "Arabic": "ar"}


def build_payload() -> dict | None:
    """Full payload including social-only fields (price, shop_address). Use for /social."""
    if not name.strip():
        st.error("Please enter a product name to continue.")
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
        "price":        social_price.strip() or None,
        "shop_address": shop_address.strip() or None,
    }
    if query.strip():
        payload["query"] = query.strip()
    return payload


def build_desc_payload() -> dict | None:
    """Payload for /generate — strips social-only fields that ContentGenerationRequest forbids."""
    payload = build_payload()
    if payload is None:
        return None
    payload.pop("price", None)
    payload.pop("shop_address", None)
    return payload


# ══════════════════════════════════════════════════════════════════════════
# CONTENT GENERATION TABS
# ══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="sec-label" style="margin-top:1.8rem">Generate content</div>', unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["Description", "Social Post", "Both", "Variety Posts"])

with tab1:
    if st.button("Generate description", key="gen_desc"):
        payload = build_desc_payload()
        if payload:
            with st.spinner("Writing description…"):
                data, code, err = call_api("generate", payload)
            if err:
                st.error(err)
            elif code == 200:
                desc    = data.get("description", {})
                bullets = data.get("feature_bullets", [])
                st.markdown('<div class="result-label" style="margin-top:0.4rem">Description</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="result-block">{desc.get("content", "")}</div>', unsafe_allow_html=True)
                if bullets:
                    st.markdown('<div class="result-label" style="margin-top:1rem">Key features</div>', unsafe_allow_html=True)
                    rows = "".join([
                        f'<div class="bullet-row"><span class="bullet-dot"></span><span>{b}</span></div>'
                        for b in bullets
                    ])
                    st.markdown(f'<div class="bullet-list">{rows}</div>', unsafe_allow_html=True)
            else:
                st.error(f"Error {code}: {data.get('detail', data)}")

with tab2:
    if st.button("Generate post", key="gen_social"):
        payload = build_payload()
        if payload:
            with st.spinner("Crafting your post…"):
                data, code, err = call_api("social", payload)
            if err:
                st.error(err)
            elif code == 200:
                post     = data.get("post", {})
                body     = post.get("post_body", "")
                hashtags = post.get("hashtags", [])
                st.markdown('<div class="result-label" style="margin-top:0.4rem">Post</div>', unsafe_allow_html=True)
                st.markdown(f'<div class="result-block">{body}</div>', unsafe_allow_html=True)
                if hashtags:
                    pills = "".join([f'<span class="tag">#{h}</span>' for h in hashtags])
                    st.markdown(f'<div class="tag-row">{pills}</div>', unsafe_allow_html=True)
            else:
                st.error(f"Error {code}: {data.get('detail', data)}")

with tab3:
    if st.button("Generate both", key="gen_both"):
        desc_payload   = build_desc_payload()
        social_payload = build_payload()
        if desc_payload and social_payload:
            col_l, col_r = st.columns(2)
            with col_l:
                st.markdown('<div class="result-label">Description</div>', unsafe_allow_html=True)
                with st.spinner("Writing…"):
                    data_g, code_g, err_g = call_api("generate", desc_payload)
                if err_g:
                    st.error(err_g)
                elif code_g == 200:
                    desc    = data_g.get("description", {})
                    bullets = data_g.get("feature_bullets", [])
                    st.markdown(f'<div class="result-block">{desc.get("content","")}</div>', unsafe_allow_html=True)
                    if bullets:
                        rows = "".join([
                            f'<div class="bullet-row"><span class="bullet-dot"></span><span>{b}</span></div>'
                            for b in bullets
                        ])
                        st.markdown('<div class="result-label" style="margin-top:0.9rem">Features</div>', unsafe_allow_html=True)
                        st.markdown(f'<div class="bullet-list">{rows}</div>', unsafe_allow_html=True)
                else:
                    st.error(f"Error {code_g}: {data_g.get('detail', data_g)}")
            with col_r:
                st.markdown('<div class="result-label">Social post</div>', unsafe_allow_html=True)
                with st.spinner("Crafting…"):
                    data_s, code_s, err_s = call_api("social", social_payload)
                if err_s:
                    st.error(err_s)
                elif code_s == 200:
                    post     = data_s.get("post", {})
                    hashtags = post.get("hashtags", [])
                    st.markdown(f'<div class="result-block">{post.get("post_body","")}</div>', unsafe_allow_html=True)
                    if hashtags:
                        pills = "".join([f'<span class="tag">#{h}</span>' for h in hashtags])
                        st.markdown(f'<div class="tag-row">{pills}</div>', unsafe_allow_html=True)
                else:
                    st.error(f"Error {code_s}: {data_s.get('detail', data_s)}")

# ══════════════════════════════════════════════════════════════════════════
# VARIETY POSTS TAB
# ══════════════════════════════════════════════════════════════════════════

with tab4:
    st.markdown(
        '<div class="hint-text" style="margin-bottom:1.2rem">'
        'Generate up to 6 distinctly styled post variants in one click — '
        'Hype Drop, Storytelling, Feature Spotlight, Value Deal, Lifestyle Fit, Minimalist. '
        'Uses the product details filled in above.'
        '</div>',
        unsafe_allow_html=True,
    )

    var_col1, var_col2, var_col3 = st.columns([1, 1, 1])
    with var_col1:
        var_count = st.selectbox(
            "How many variants?",
            options=[2, 3, 4, 5, 6],
            index=2,
            key="var_count",
        )
    with var_col2:
        var_language = st.selectbox(
            "Language",
            ["English", "Bengali (বাংলা)", "Arabic"],
            key="var_language",
        )
    with var_col3:
        var_region = st.selectbox(
            "Region",
            ["BD", "IN", "US", "UK", "AE"],
            key="var_region",
        )

    if st.button("Generate varieties", key="gen_variants"):
        if not name.strip():
            st.error("Please enter a product name in the Product details section above.")
        else:
            specs = [s.strip() for s in specs_raw.splitlines() if s.strip()]
            var_lang_map = {"English": "english", "Bengali (বাংলা)": "Bengali", "Arabic": "ar"}

            variants_payload = {
                "product_data": {
                    "name":           name.strip(),
                    "category":       category.strip() or None,
                    "brand":          brand.strip() or None,
                    "specifications": specs,
                    "price":          price if price > 0 else None,
                },
                "price":        social_price.strip() or None,
                "shop_address": shop_address.strip() or None,
                "region":       var_region,
                "language":     var_lang_map.get(var_language, "english"),
                "count":        var_count,
            }

            with st.spinner(f"Generating {var_count} post variants…"):
                data, code, err = call_api("variants", variants_payload)

            if err:
                st.error(err)
            elif code == 200:
                variants = data.get("variants", [])

                if not variants:
                    st.warning("No variants returned. Try again.")
                else:
                    st.markdown(
                        f'<div class="result-label" style="margin-top:0.6rem">' +
                        f"{len(variants)} variants generated — pick your favourite" +
                        '</div>',
                        unsafe_allow_html=True,
                    )

                    badge_colors = [
                        "#18181b", "#2d6a4f", "#1d3557", "#7b2d8b", "#b5451b", "#1a535c"
                    ]

                    for i, variant in enumerate(variants):
                        label    = variant.get("label", f"Variant {i+1}")
                        body     = variant.get("post_body", "")
                        hashtags = variant.get("hashtags", [])
                        chars    = variant.get("char_count", len(body))
                        color    = badge_colors[i % len(badge_colors)]

                        st.markdown(
                            f'<div style="display:flex;align-items:center;gap:0.7rem;margin:1.6rem 0 0.5rem;">' +
                            f'<span style="background:{color};color:#fff;font-family:JetBrains Mono,monospace;' +
                            f'font-size:0.62rem;letter-spacing:0.1em;text-transform:uppercase;' +
                            f'padding:0.25rem 0.65rem;border-radius:6px;">{label}</span>' +
                            f'<span style="font-family:JetBrains Mono,monospace;font-size:0.62rem;' +
                            f'color:#c0c0bc;">{chars} chars</span>' +
                            '</div>',
                            unsafe_allow_html=True,
                        )

                        st.markdown(
                            f'<div class="result-block">{body}</div>',
                            unsafe_allow_html=True,
                        )

                        if hashtags:
                            pills = "".join([f'<span class="tag">#{h}</span>' for h in hashtags])
                            st.markdown(f'<div class="tag-row">{pills}</div>', unsafe_allow_html=True)

                        with st.expander(f"📋 Copy variant {i+1} — {label}"):
                            st.text_area(
                                label="Post body",
                                value=body,
                                height=200,
                                key=f"copy_{i}",
                            )
                            if hashtags:
                                st.text_input(
                                    label="Hashtags",
                                    value=" ".join([f"#{h}" for h in hashtags]),
                                    key=f"copy_tags_{i}",
                                )
            else:
                st.error(f"Error {code}: {data.get('detail', data)}")


# ══════════════════════════════════════════════════════════════════════════
# RAG SEARCH
# ══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
st.markdown('<div class="sec-label">RAG Search</div>', unsafe_allow_html=True)

rag_query = st.text_input(
    "What are you looking for?",
    key="rag_query",
    placeholder="e.g. suggest a budget laptop under 50,000 BDT with good battery life",
)

if st.button("Search", key="rag_search"):
    if not rag_query.strip():
        st.error("Please enter a search query.")
    else:
        payload = {"query": rag_query.strip(), "org_id": KEY_INPUT, "top_k": 5}
        with st.spinner("Searching your inventory…"):
            data, code, err = call_search_api("rag", payload)
        if err:
            st.error(err)
        elif code == 200:
            answer  = data.get("answer", "")
            sources = data.get("sources", [])
            st.markdown('<div class="result-label" style="margin-top:0.6rem">Answer</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="rag-answer">{answer}</div>', unsafe_allow_html=True)
            render_sources(sources)
        else:
            st.error(f"Error {code}: {data.get('detail', data)}")


# ══════════════════════════════════════════════════════════════════════════
# VOICE SEARCH
# ══════════════════════════════════════════════════════════════════════════

st.markdown('<div class="section-gap"></div>', unsafe_allow_html=True)
st.markdown('<div class="sec-label">Voice Search</div>', unsafe_allow_html=True)

voice_col1, voice_col2 = st.columns([4, 1])
with voice_col1:
    voice_url = st.text_input(
        "Audio file URL",
        key="voice_url",
        placeholder="Paste a Cloudflare R2 URL — e.g. https://pub-xxx.r2.dev/query.mp3",
    )
with voice_col2:
    voice_lang = st.selectbox(
        "Language",
        options=["en", "bn", "ar", "hi", "zh", "fr", "de", "es"],
        key="voice_lang",
    )

if st.button("Transcribe & Search", key="voice_search"):
    if not voice_url.strip():
        st.error("Please paste an audio URL first.")
    else:
        payload = {
            "file_url": voice_url.strip(),
            "org_id":   KEY_INPUT,
            "language": voice_lang,
            "top_k":    5,
        }
        with st.spinner("Transcribing and searching…"):
            try:
                resp = requests.post(
                    VOICE_API_URL,
                    json=payload,
                    headers={
                        "X-API-Key":    API_KEY,
                        "X-Key-Input":  KEY_INPUT,
                        "Content-Type": "application/json",
                    },
                    timeout=60,
                )
                try:
                    data = resp.json()
                except Exception:
                    data = {"raw": resp.text}
                code, err = resp.status_code, ""
            except requests.exceptions.ConnectionError:
                data, code, err = None, 0, "Can't reach the server — is it running?"
            except requests.exceptions.Timeout:
                data, code, err = None, 0, "Request timed out. Try again."
            except Exception as e:
                data, code, err = None, 0, str(e)

        if err:
            st.error(err)
        elif code == 200:
            transcript = data.get("transcript", "")
            answer     = data.get("answer", "")
            sources    = data.get("sources", [])

            if transcript:
                st.markdown(
                    f'<div class="transcript-pill">'
                    f'<span class="t-label">You said</span>'
                    f'&nbsp;{transcript}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            st.markdown('<div class="result-label">Answer</div>', unsafe_allow_html=True)
            st.markdown(f'<div class="rag-answer">{answer}</div>', unsafe_allow_html=True)
            render_sources(sources)

        elif code == 400:
            st.error(f"Bad request: {data.get('detail', 'Invalid audio or empty transcript.')}")
        elif code == 413:
            st.error("Audio file is too large (25 MB limit).")
        elif code == 429:
            st.warning("Rate limit hit — wait a moment and try again.")
        elif code == 503:
            st.error("AI service is currently unavailable. Try again shortly.")
        else:
            st.error(f"Error {code}: {data.get('detail', data)}")