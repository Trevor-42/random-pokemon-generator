import json
import csv
import io
import streamlit as st
import random
import requests
import base64
from datetime import datetime
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor, as_completed
from streamlit_local_storage import LocalStorage

TYPE_COLORS = {
    'Normal': '#A8A878', 'Fire': '#F08030', 'Water': '#6890F0',
    'Electric': '#F8D030', 'Grass': '#78C850', 'Ice': '#98D8D8',
    'Fighting': '#C03028', 'Poison': '#A040A0', 'Ground': '#E0C068',
    'Flying': '#A890F0', 'Psychic': '#F85888', 'Bug': '#A8B820',
    'Rock': '#B8A038', 'Ghost': '#705898', 'Dragon': '#7038F8',
    'Dark': '#705848', 'Steel': '#B8B8D0', 'Fairy': '#EE99AC',
}
STAT_NAMES = {
    'hp': 'HP', 'attack': 'Atk', 'defense': 'Def',
    'special-attack': 'Sp.Atk', 'special-defense': 'Sp.Def', 'speed': 'Spd'
}
GENERATIONS = {
    "Gen 1": (1, 151), "Gen 2": (152, 251), "Gen 3": (252, 386),
    "Gen 4": (387, 493), "Gen 5": (494, 649), "Gen 6": (650, 721),
    "Gen 7": (722, 809), "Gen 8": (810, 905), "Gen 9": (906, 1025),
}

CONDITION_MULT = {"NM": 1.0, "LP": 0.85, "MP": 0.70, "HP": 0.50, "Damaged": 0.30}
CONDITION_COLORS = {"NM": "#4CAF50", "LP": "#8BC34A", "MP": "#FFC107", "HP": "#FF5722", "Damaged": "#9E9E9E"}

# --- eBay OAuth Config ---
EBAY_AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SCOPES = "https://api.ebay.com/oauth/api_scope"
SHOW_EBAY = False

# --- Page Config (must be first) ---
st.set_page_config(page_title="Pokémon Card Vault", layout="wide", page_icon="🔥")

# --- eBay OAuth Helpers ---

def get_ebay_auth_url():
    client_id = st.secrets.get("EBAY_CLIENT_ID")
    redirect_uri = st.secrets.get("EBAY_REDIRECT_URI")
    if not client_id or not redirect_uri:
        return None
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": EBAY_SCOPES,
    }
    return f"{EBAY_AUTH_URL}?{urlencode(params)}"

def exchange_code_for_token(code):
    client_id = st.secrets.get("EBAY_CLIENT_ID")
    client_secret = st.secrets.get("EBAY_CLIENT_SECRET")
    redirect_uri = st.secrets.get("EBAY_REDIRECT_URI")
    if not client_id or not client_secret or not redirect_uri:
        return None

    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = requests.post(
        EBAY_TOKEN_URL,
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
    )
    if response.status_code == 200:
        return response.json()
    st.error(f"eBay token exchange failed ({response.status_code}): {response.text}")
    return None

def refresh_ebay_token(refresh_token):
    client_id = st.secrets.get("EBAY_CLIENT_ID")
    client_secret = st.secrets.get("EBAY_CLIENT_SECRET")
    if not client_id or not client_secret:
        return None

    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    response = requests.post(
        EBAY_TOKEN_URL,
        headers={
            "Authorization": f"Basic {encoded}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "scope": EBAY_SCOPES,
        },
    )
    if response.status_code == 200:
        return response.json()
    return None

def get_ebay_token():
    """Returns a valid access token from session_state, refreshing if needed."""
    if "ebay_access_token" not in st.session_state:
        return None

    if st.session_state.get("ebay_token_expired"):
        refresh_token = st.session_state.get("ebay_refresh_token")
        if refresh_token:
            token_data = refresh_ebay_token(refresh_token)
            if token_data:
                st.session_state.ebay_access_token = token_data["access_token"]
                st.session_state.ebay_token_expired = False
                if "refresh_token" in token_data:
                    st.session_state.ebay_refresh_token = token_data["refresh_token"]
            else:
                del st.session_state["ebay_access_token"]
                return None

    return st.session_state.get("ebay_access_token")

# --- Handle OAuth Callback ---
query_params = st.query_params
if "code" in query_params and "ebay_access_token" not in st.session_state:
    with st.spinner("Connecting to eBay..."):
        token_data = exchange_code_for_token(query_params["code"])
        if token_data:
            st.session_state.ebay_access_token = token_data["access_token"]
            st.session_state.ebay_refresh_token = token_data.get("refresh_token")
            st.session_state.ebay_token_expired = False
            st.query_params.clear()
            st.rerun()

# --- Pokémon API Functions ---

@st.cache_data(ttl=86400)
def get_total_pokemon():
    try:
        response = requests.get("https://pokeapi.co/api/v2/pokemon-species/")
        if response.status_code == 200:
            return response.json()['count']
    except requests.exceptions.RequestException:
        pass
    return 1025

@st.cache_data(ttl=86400)
def get_all_pokemon_list():
    try:
        response = requests.get("https://pokeapi.co/api/v2/pokemon?limit=1025&offset=0")
        if response.status_code == 200:
            results = response.json()['results']
            return [
                {
                    "id": int(r['url'].rstrip('/').split('/')[-1]),
                    "name": r['name'].replace('-', ' ').title()
                }
                for r in results
            ]
    except requests.exceptions.RequestException:
        pass
    return []

@st.cache_data(ttl=3600)
def fetch_pokemon_data(identifier):
    clean_id = str(identifier).strip().lower().replace(" ", "-")
    try:
        response = requests.get(f"https://pokeapi.co/api/v2/pokemon/{clean_id}")
        if response.status_code == 200:
            data = response.json()
            pokemon_name = data['species']['name'].replace('-', ' ').title()
            types = [t['type']['name'].capitalize() for t in data['types']]
            sprite_url = data['sprites']['other']['official-artwork']['front_default']
            stats = {s['stat']['name']: s['base_stat'] for s in data['stats']}
            return {
                "name": pokemon_name,
                "id": data['id'],
                "types": types,
                "sprite": sprite_url,
                "stats": stats,
                "error": None
            }
        elif response.status_code == 404:
            return {"error": f"Could not find a Pokémon named '{identifier}'. Check your spelling!"}
        else:
            return {"error": "API Error. Please try again later."}
    except requests.exceptions.RequestException:
        return {"error": "Connection error to PokéAPI."}

@st.cache_data(ttl=86400)
def get_evolution_chain(species_id):
    """Fetch evolution chain for a Pokémon species."""
    try:
        spec_resp = requests.get(f"https://pokeapi.co/api/v2/pokemon-species/{species_id}")
        if spec_resp.status_code != 200:
            return []
        chain_url = spec_resp.json().get('evolution_chain', {}).get('url')
        if not chain_url:
            return []
        chain_resp = requests.get(chain_url)
        if chain_resp.status_code != 200:
            return []

        chain_data = chain_resp.json().get('chain', {})
        evos = []

        def walk(node):
            species = node.get('species', {})
            name = species.get('name', '').replace('-', ' ').title()
            sid = int(species.get('url', '/0/').rstrip('/').split('/')[-1])
            evos.append({"name": name, "id": sid})
            for child in node.get('evolves_to', []):
                walk(child)

        walk(chain_data)
        return evos
    except requests.exceptions.RequestException:
        return []

@st.cache_data(ttl=3600)
def get_tcg_cards(pokemon_name, top_n=10, api_key=""):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    if api_key:
        headers['X-Api-Key'] = api_key
    try:
        response = requests.get(
            "https://api.pokemontcg.io/v2/cards",
            headers=headers,
            params={"q": f'name:{pokemon_name}*', "pageSize": 250},
        )
        if response.status_code != 200:
            return None, 0

        cards = response.json().get('data', [])
        card_prices = []
        for card in cards:
            tcgplayer = card.get('tcgplayer', {})
            prices = tcgplayer.get('prices', {})
            highest_price = 0
            price_low = None
            price_high = None
            for price_data in prices.values():
                market_price = price_data.get('market')
                if market_price is not None and market_price > highest_price:
                    highest_price = market_price
                low_val = price_data.get('low')
                high_val = price_data.get('high')
                if low_val is not None:
                    price_low = low_val if price_low is None else min(price_low, low_val)
                if high_val is not None:
                    price_high = high_val if price_high is None else max(price_high, high_val)
            if highest_price > 0:
                card_prices.append({
                    'name': card.get('name', pokemon_name),
                    'set': card.get('set', {}).get('name', 'Unknown Set'),
                    'price': highest_price,
                    'image': card.get('images', {}).get('small', ''),
                    'url': tcgplayer.get('url', '#'),
                    'rarity': card.get('rarity', 'Unknown'),
                    'price_low': price_low,
                    'price_high': price_high,
                })
        card_prices.sort(key=lambda x: x['price'], reverse=True)
        return card_prices[:top_n], len(card_prices)
    except requests.exceptions.RequestException:
        return None, 0

@st.cache_data(ttl=86400)
def get_all_types():
    try:
        response = requests.get("https://pokeapi.co/api/v2/type/")
        if response.status_code == 200:
            types = response.json().get('results', [])
            return sorted([
                t['name'].capitalize() for t in types
                if t['name'] not in ('unknown', 'shadow')
            ])
    except requests.exceptions.RequestException:
        pass
    return []

@st.cache_data(ttl=86400)
def get_pokemon_by_type(type_name):
    try:
        response = requests.get(f"https://pokeapi.co/api/v2/type/{type_name.lower()}")
        if response.status_code == 200:
            return [p['pokemon']['name'] for p in response.json()['pokemon']]
    except requests.exceptions.RequestException:
        pass
    return []

@st.cache_data(ttl=86400)
def get_tcg_sets(api_key=""):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    if api_key:
        headers['X-Api-Key'] = api_key
    try:
        response = requests.get(
            "https://api.pokemontcg.io/v2/sets",
            headers=headers,
            params={"pageSize": 250}
        )
        if response.status_code == 200:
            sets = response.json().get('data', [])
            return sorted(sets, key=lambda s: s.get('releaseDate', ''), reverse=True)
    except requests.exceptions.RequestException:
        pass
    return []

@st.cache_data(ttl=3600)
def get_set_cards(set_id, api_key=""):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    if api_key:
        headers['X-Api-Key'] = api_key
    try:
        response = requests.get(
            "https://api.pokemontcg.io/v2/cards",
            headers=headers,
            params={"q": f"set.id:{set_id}", "pageSize": 250, "orderBy": "number"}
        )
        if response.status_code == 200:
            return response.json().get('data', [])
    except requests.exceptions.RequestException:
        pass
    return []

def type_badge(type_name):
    color = TYPE_COLORS.get(type_name, '#888888')
    return (f'<span style="background:{color}22; color:{color}; border:1px solid {color}66; '
            f'padding:3px 12px; border-radius:4px; font-weight:700; font-size:0.78em; '
            f'margin-right:5px; letter-spacing:0.08em; text-transform:uppercase; '
            f'font-family:\'Chakra Petch\',sans-serif;">'
            f'{type_name}</span>')

def check_ebay_sold_listings(card_name, set_name, token):
    query = f"{card_name} {set_name} Pokemon card"
    try:
        response = requests.get(
            "https://api.ebay.com/buy/marketplace_insights/v1_beta/item_sales/search",
            headers={
                "Authorization": f"Bearer {token}",
                "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
            },
            params={"q": query, "limit": 10},
        )
    except requests.exceptions.RequestException:
        return None

    if response.status_code == 401:
        st.session_state.ebay_token_expired = True
        return None
    if response.status_code != 200:
        return None

    sales = response.json().get("itemSales", [])
    prices = [
        float(sale["lastSoldPrice"]["value"])
        for sale in sales
        if sale.get("lastSoldPrice", {}).get("value")
    ]
    if not prices:
        return None

    return {
        "avg": sum(prices) / len(prices),
        "count": len(prices),
        "low": min(prices),
        "high": max(prices),
    }

# --- UI ---

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Chakra+Petch:wght@400;500;600;700&family=Sora:wght@300;400;500;600;700&display=swap');

:root {
    --vault-bg: #08080e;
    --vault-surface: #0f0f1a;
    --vault-card: #131322;
    --vault-border: #1e1e38;
    --vault-hover: #1a1a35;
    --fire: #ff6b35;
    --fire-dim: #ff6b3522;
    --ember: #ff8c42;
    --gold: #ffc857;
    --teal: #00e5a0;
    --teal-dim: #00e5a022;
    --text-primary: #e8e8f0;
    --text-secondary: #6e6e8a;
    --text-muted: #44445a;
}

/* ── Global ── */
html, body, [data-testid="stAppViewContainer"],
[data-testid="stApp"] {
    background-color: var(--vault-bg) !important;
    color: var(--text-primary) !important;
    font-family: 'Sora', sans-serif !important;
}
[data-testid="stMain"] > div { background: var(--vault-bg) !important; }
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stToolbar"] { display: none !important; }
.block-container { max-width: 1200px; padding-top: 2rem !important; }

/* ── Typography ── */
h1, h2, h3, .vault-title {
    font-family: 'Chakra Petch', sans-serif !important;
    letter-spacing: -0.02em;
}
h1 { color: var(--text-primary) !important; font-weight: 700 !important; }
h2 { color: var(--text-primary) !important; font-weight: 600 !important; font-size: 1.4rem !important; }
h3 { color: var(--text-primary) !important; font-weight: 600 !important; }
p, span, label, .stMarkdown { color: var(--text-primary) !important; }
[data-testid="stCaptionContainer"] { color: var(--text-secondary) !important; }
[data-testid="stCaptionContainer"] * { color: var(--text-secondary) !important; }

/* ── Tabs ── */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
    background: var(--vault-surface) !important;
    border-radius: 8px !important;
    padding: 4px !important;
    gap: 2px !important;
    border: 1px solid var(--vault-border) !important;
}
[data-testid="stTabs"] [data-baseweb="tab"] {
    background: transparent !important;
    color: var(--text-secondary) !important;
    border-radius: 6px !important;
    font-family: 'Chakra Petch', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.82rem !important;
    letter-spacing: 0.03em !important;
    padding: 8px 16px !important;
    transition: all 0.2s ease !important;
}
[data-testid="stTabs"] [data-baseweb="tab"][aria-selected="true"] {
    background: var(--fire-dim) !important;
    color: var(--fire) !important;
    border-bottom: none !important;
}
[data-testid="stTabs"] [data-baseweb="tab"]:hover {
    background: var(--vault-hover) !important;
    color: var(--text-primary) !important;
}
[data-testid="stTabs"] [data-baseweb="tab-highlight"],
[data-testid="stTabs"] [data-baseweb="tab-border"] { display: none !important; }

/* ── Buttons ── */
.stButton > button {
    background: var(--vault-surface) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--vault-border) !important;
    border-radius: 6px !important;
    font-family: 'Sora', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.82rem !important;
    transition: all 0.2s ease !important;
    letter-spacing: 0.02em;
}
.stButton > button:hover {
    background: var(--vault-hover) !important;
    border-color: var(--fire) !important;
    color: var(--fire) !important;
    box-shadow: 0 0 20px var(--fire-dim) !important;
}
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(135deg, var(--fire), var(--ember)) !important;
    color: #fff !important;
    border: none !important;
    font-weight: 600 !important;
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {
    box-shadow: 0 4px 24px #ff6b3544 !important;
    transform: translateY(-1px);
}
.stDownloadButton > button {
    background: var(--vault-surface) !important;
    color: var(--gold) !important;
    border: 1px solid var(--gold)33 !important;
    border-radius: 6px !important;
    font-family: 'Sora', sans-serif !important;
}
.stDownloadButton > button:hover {
    border-color: var(--gold) !important;
    box-shadow: 0 0 16px #ffc85722 !important;
}
.stLinkButton > a {
    background: var(--vault-surface) !important;
    color: var(--teal) !important;
    border: 1px solid var(--teal)33 !important;
    border-radius: 6px !important;
    font-family: 'Sora', sans-serif !important;
    font-size: 0.82rem !important;
    transition: all 0.2s ease !important;
}
.stLinkButton > a:hover {
    border-color: var(--teal) !important;
    box-shadow: 0 0 16px var(--teal-dim) !important;
}

/* ── Inputs ── */
[data-testid="stTextInput"] input,
[data-testid="stNumberInput"] input {
    background: var(--vault-surface) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--vault-border) !important;
    border-radius: 6px !important;
    font-family: 'Sora', sans-serif !important;
}
[data-testid="stTextInput"] input:focus,
[data-testid="stNumberInput"] input:focus {
    border-color: var(--fire) !important;
    box-shadow: 0 0 12px var(--fire-dim) !important;
}
[data-baseweb="select"] > div {
    background: var(--vault-surface) !important;
    border: 1px solid var(--vault-border) !important;
    border-radius: 6px !important;
    color: var(--text-primary) !important;
}
[data-baseweb="popover"] {
    background: var(--vault-card) !important;
    border: 1px solid var(--vault-border) !important;
}
[data-baseweb="popover"] li {
    color: var(--text-primary) !important;
}
[data-baseweb="popover"] li:hover {
    background: var(--vault-hover) !important;
}

/* ── Metrics ── */
[data-testid="stMetric"] {
    background: var(--vault-surface) !important;
    border: 1px solid var(--vault-border) !important;
    border-radius: 8px !important;
    padding: 16px !important;
}
[data-testid="stMetricValue"] {
    font-family: 'Chakra Petch', sans-serif !important;
    color: var(--gold) !important;
    font-weight: 700 !important;
}
[data-testid="stMetricLabel"] {
    color: var(--text-secondary) !important;
    font-family: 'Sora', sans-serif !important;
    text-transform: uppercase !important;
    font-size: 0.7rem !important;
    letter-spacing: 0.1em !important;
}

/* ── Progress bars ── */
.stProgress > div > div > div {
    background: linear-gradient(90deg, var(--fire), var(--ember), var(--gold)) !important;
    border-radius: 4px !important;
}
.stProgress > div > div {
    background: var(--vault-surface) !important;
    border-radius: 4px !important;
}

/* ── Expander ── */
[data-testid="stExpander"] {
    background: var(--vault-surface) !important;
    border: 1px solid var(--vault-border) !important;
    border-radius: 8px !important;
}
[data-testid="stExpander"] summary {
    color: var(--text-primary) !important;
    font-family: 'Chakra Petch', sans-serif !important;
}
[data-testid="stExpander"] details {
    border: none !important;
}

/* ── Divider ── */
hr { border-color: var(--vault-border) !important; opacity: 0.5; }

/* ── Alerts ── */
[data-testid="stAlert"] {
    background: var(--vault-surface) !important;
    border: 1px solid var(--vault-border) !important;
    border-radius: 8px !important;
    color: var(--text-primary) !important;
}

/* ── Images — card hover glow ── */
[data-testid="stImage"] img {
    border-radius: 6px;
    transition: all 0.3s ease;
}
[data-testid="stImage"]:hover img {
    transform: scale(1.03);
    filter: brightness(1.08);
}

/* ── Spinner ── */
.stSpinner > div { color: var(--fire) !important; }

/* ── File uploader ── */
[data-testid="stFileUploader"] {
    background: var(--vault-surface) !important;
    border: 1px dashed var(--vault-border) !important;
    border-radius: 8px !important;
}
[data-testid="stFileUploader"] * { color: var(--text-secondary) !important; }

/* ── Scrollbar ── */
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: var(--vault-bg); }
::-webkit-scrollbar-thumb { background: var(--vault-border); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--fire); }

/* ── Charts ── */
[data-testid="stVegaLiteChart"] { border-radius: 8px; overflow: hidden; }

/* ── Column containers ── */
[data-testid="column"] { transition: all 0.2s ease; }

/* ── Form ── */
[data-testid="stForm"] {
    background: var(--vault-surface) !important;
    border: 1px solid var(--vault-border) !important;
    border-radius: 8px !important;
    padding: 1rem !important;
}
.stFormSubmitButton > button {
    background: linear-gradient(135deg, var(--fire), var(--ember)) !important;
    color: #fff !important;
    border: none !important;
    font-weight: 600 !important;
}

/* ── Mobile ── */
@media screen and (max-width: 640px) {
    [data-testid="stHorizontalBlock"] { flex-wrap: wrap; }
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        width: 100% !important; flex: 1 1 100% !important; min-width: 100% !important;
    }
    [data-testid="stImage"] img { max-width: 140px !important; }
    h1 { font-size: 1.4rem !important; }
    h2 { font-size: 1.1rem !important; }
    [data-testid="stTabs"] [data-baseweb="tab"] { font-size: 0.7rem !important; padding: 6px 10px !important; }
}

/* ── Print ── */
@media print {
    [data-testid="stSidebar"], [data-testid="stHeader"],
    [data-testid="stToolbar"], .stButton, .stSelectbox,
    .stTextInput, .stTabs [data-baseweb="tab-list"],
    [data-testid="stDecoration"] { display: none !important; }
    [data-testid="stAppViewContainer"] { padding: 0 !important; background: #fff !important; }
    * { color: #111 !important; }
    [data-testid="stImage"] img { max-width: 60px !important; }
    @page { margin: 0.5in; size: landscape; }
}
</style>
""", unsafe_allow_html=True)

st.markdown(
    '<h1 style="font-family:\'Chakra Petch\',sans-serif; font-weight:700; '
    'background:linear-gradient(135deg,#ff6b35,#ffc857); -webkit-background-clip:text; '
    '-webkit-text-fill-color:transparent; font-size:2.2rem; margin-bottom:0.5rem; '
    'letter-spacing:-0.03em;">POKÉMON CARD VAULT</h1>'
    '<p style="color:#6e6e8a; font-family:\'Sora\',sans-serif; font-size:0.85rem; '
    'letter-spacing:0.08em; text-transform:uppercase; margin-top:-0.5rem;">Track · Trade · Collect</p>',
    unsafe_allow_html=True
)

# --- LocalStorage init ---
localS = LocalStorage()
_binder_raw = localS.getItem("pokedex_binder")
if "binder_initialized" not in st.session_state:
    if _binder_raw:
        try:
            st.session_state.binder = json.loads(_binder_raw)
            st.session_state.binder_initialized = True
        except (json.JSONDecodeError, TypeError):
            st.session_state.binder = {}
    else:
        st.session_state.binder = {}

# Wishlist localStorage
_wishlist_raw = localS.getItem("pokemon_wishlist")
if "wishlist_initialized" not in st.session_state:
    if _wishlist_raw:
        try:
            st.session_state.wishlist = json.loads(_wishlist_raw)
            st.session_state.wishlist_initialized = True
        except (json.JSONDecodeError, TypeError):
            st.session_state.wishlist = {}
    else:
        st.session_state.wishlist = {}

if st.session_state.get("binder_dirty"):
    localS.setItem("pokedex_binder", json.dumps(st.session_state.binder))
    st.session_state.binder_dirty = False

if st.session_state.get("wishlist_dirty"):
    localS.setItem("pokemon_wishlist", json.dumps(st.session_state.wishlist))
    st.session_state.wishlist_dirty = False

# --- eBay banner ---
ebay_token = get_ebay_token() if SHOW_EBAY else None
if SHOW_EBAY:
    if ebay_token:
        col_status, col_disconnect = st.columns([4, 1])
        with col_status:
            st.success("✅ eBay account connected")
        with col_disconnect:
            if st.button("Disconnect eBay"):
                for key in ["ebay_access_token", "ebay_refresh_token", "ebay_token_expired"]:
                    st.session_state.pop(key, None)
                st.rerun()
    else:
        col_status, col_connect = st.columns([4, 1])
        with col_status:
            st.warning("⚠️ eBay not connected — sold price data unavailable")
        with col_connect:
            auth_url = get_ebay_auth_url()
            if auth_url:
                st.link_button("Connect eBay", auth_url, type="primary")
            else:
                st.caption("Add EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_REDIRECT_URI to secrets")

# --- Session state init ---
if 'current_pokemon' not in st.session_state:
    st.session_state.current_pokemon = None
if 'search_history' not in st.session_state:
    st.session_state.search_history = []
if 'binder_page' not in st.session_state:
    st.session_state.binder_page = 0
if 'binder_active' not in st.session_state:
    st.session_state.binder_active = None
if 'compare_list' not in st.session_state:
    st.session_state.compare_list = []

# --- URL param loading ---
_url_pokemon = st.query_params.get("pokemon")
if _url_pokemon and st.session_state.current_pokemon is None:
    with st.spinner("Loading Pokémon..."):
        st.session_state.current_pokemon = fetch_pokemon_data(_url_pokemon)

# --- Top-level tabs ---
main_tab_search, main_tab_binder, main_tab_top, main_tab_compare, main_tab_wishlist, main_tab_stats = st.tabs([
    "🔍 Search & Card Market", "📒 Pokédex Binder", "💎 Top 1025",
    "⚖️ Compare", "💫 Wishlist", "📊 Stats"
])

# ============================================================
# SEARCH & CARD MARKET TAB
# ============================================================
with main_tab_search:
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Surprise Me!")
        selected_type = st.selectbox("Filter by type", ["Any type"] + get_all_types(), label_visibility="collapsed")
        if st.button("Catch a Random Pokémon", type="primary", use_container_width=True):
            with st.spinner("Searching the tall grass..."):
                if selected_type == "Any type":
                    total_pokemon = get_total_pokemon()
                    random_id = random.randint(1, total_pokemon)
                    st.session_state.current_pokemon = fetch_pokemon_data(random_id)
                else:
                    type_pokemon = get_pokemon_by_type(selected_type)
                    if type_pokemon:
                        chosen = random.choice(type_pokemon)
                        st.session_state.current_pokemon = fetch_pokemon_data(chosen)
                    else:
                        st.warning(f"No Pokémon found for type {selected_type}.")

    with col2:
        st.subheader("Look Up Pokémon")
        with st.form("search_form"):
            search_query = st.text_input("Enter a Pokémon name (e.g., Charizard, Lugia):", label_visibility="collapsed", placeholder="Enter a Pokémon name...")
            submitted = st.form_submit_button("Search", use_container_width=True)
            if submitted and search_query:
                with st.spinner(f"Looking up {search_query}..."):
                    st.session_state.current_pokemon = fetch_pokemon_data(search_query)

    if st.session_state.search_history:
        st.caption("Recent:")
        history_to_show = st.session_state.search_history[-5:]
        history_cols = st.columns(len(history_to_show))
        for idx, entry in enumerate(history_to_show):
            with history_cols[idx]:
                if st.button(entry['name'], key=f"history_{entry['id']}"):
                    st.session_state.current_pokemon = fetch_pokemon_data(entry['id'])

    st.divider()

    if st.session_state.current_pokemon:
        pokemon = st.session_state.current_pokemon

        if pokemon.get("error"):
            st.error(pokemon["error"])
        else:
            st.query_params["pokemon"] = str(pokemon['id'])
            history = st.session_state.search_history
            history = [h for h in history if h['id'] != pokemon['id']]
            history.append({'name': pokemon['name'], 'id': pokemon['id']})
            st.session_state.search_history = history[-5:]

            primary_type = pokemon['types'][0]
            accent_color = TYPE_COLORS.get(primary_type, '#888888')

            tab_info, tab_cards = st.tabs(["⚡ Pokémon Info", "💰 Card Market"])

            with tab_info:
                poke_col1, poke_col2 = st.columns([1, 3])
                with poke_col1:
                    if pokemon['sprite']:
                        st.image(pokemon['sprite'], width=200)
                with poke_col2:
                    st.markdown(
                        f'<h2 style="font-family:\'Chakra Petch\',sans-serif; color:{accent_color}; margin-bottom:0.3rem;">'
                        f'{pokemon["name"]} '
                        f'<span style="color:#6e6e8a; font-size:0.65em; font-weight:400">#{pokemon["id"]:04d}</span></h2>',
                        unsafe_allow_html=True
                    )
                    st.markdown("".join(type_badge(t) for t in pokemon['types']), unsafe_allow_html=True)

                    st.markdown("**Base Stats**")
                    stat_cols = st.columns(6)
                    for col_idx, (stat_key, stat_label) in enumerate(STAT_NAMES.items()):
                        val = pokemon['stats'].get(stat_key, 0)
                        with stat_cols[col_idx]:
                            st.metric(stat_label, val)
                            st.progress(min(val / 255, 1.0))

                # Evolution Chain
                evo_chain = get_evolution_chain(pokemon['id'])
                if evo_chain and len(evo_chain) > 1:
                    st.markdown("**Evolution Chain**")
                    evo_cols = st.columns(len(evo_chain))
                    for evo_idx, evo in enumerate(evo_chain):
                        with evo_cols[evo_idx]:
                            evo_sprite = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{evo['id']}.png"
                            st.image(evo_sprite, width=80)
                            is_current = evo['id'] == pokemon['id']
                            label = f"**{evo['name']}**" if is_current else evo['name']
                            st.caption(label)
                            if not is_current:
                                if st.button(f"→ {evo['name']}", key=f"evo_{evo['id']}"):
                                    st.session_state.current_pokemon = fetch_pokemon_data(evo['id'])
                                    st.rerun()

            with tab_cards:
                st.subheader(f"Top Valuable Cards for {pokemon['name']}")
                api_key = st.secrets.get("POKEMONTCG_API_KEY", "")
                with st.spinner("Pulling data from TCGplayer..."):
                    top_cards, total_cards = get_tcg_cards(pokemon['name'], top_n=20, api_key=api_key)

                    if not top_cards:
                        st.warning("No pricing data found for this Pokémon.")
                    else:
                        st.caption(f"Showing top {len(top_cards)} of {total_cards} cards with pricing data")
                        sort_order = st.selectbox("Sort", ["Price: High → Low", "Price: Low → High"], label_visibility="collapsed")
                        if sort_order == "Price: Low → High":
                            top_cards = sorted(top_cards, key=lambda x: x['price'])

                        card_columns = st.columns(min(len(top_cards), 3))
                        for idx, card in enumerate(top_cards):
                            with card_columns[idx % 3]:
                                if card['image']:
                                    st.image(card['image'], use_container_width=True)
                                st.markdown(f"**{card['name']}**")
                                st.caption(f"Set: {card['set']}")
                                st.caption(f"Rarity: {card['rarity']}")
                                st.write(f"TCG Market: **${card['price']:.2f}**")
                                if card.get('price_low') and card.get('price_high'):
                                    st.caption(f"Range: ${card['price_low']:.2f} – ${card['price_high']:.2f}")

                                if SHOW_EBAY:
                                    if ebay_token:
                                        ebay_data = check_ebay_sold_listings(card['name'], card['set'], ebay_token)
                                        if ebay_data:
                                            st.caption(
                                                f"eBay Sold ({ebay_data['count']} sales): "
                                                f"avg **${ebay_data['avg']:.2f}** "
                                                f"(${ebay_data['low']:.2f}–${ebay_data['high']:.2f})"
                                            )
                                        else:
                                            st.caption("eBay: No recent sales found")
                                    else:
                                        st.caption("eBay: Connect above to see sold prices")

                                st.link_button("View on TCGplayer", card['url'])

# ============================================================
# POKÉDEX BINDER TAB
# ============================================================
with main_tab_binder:
    binder = st.session_state.binder
    owned_count = len(binder)
    total_value = sum(v.get('card_value', 0) for v in binder.values())

    # Summary
    sum_col1, sum_col2, sum_col3 = st.columns(3)
    with sum_col1:
        st.metric("Collected", f"{owned_count} / 1025")
    with sum_col2:
        st.metric("Total Value", f"${total_value:.2f}")
    with sum_col3:
        st.metric("Missing", f"{1025 - owned_count}")
    st.progress(owned_count / 1025)

    # Export / Import / Refresh / Print
    api_key = st.secrets.get("POKEMONTCG_API_KEY", "")
    action_col1, action_col2, action_col3, action_col4 = st.columns(4)
    with action_col1:
        if st.button("🔄 Refresh All Prices", disabled=owned_count == 0, use_container_width=True):
            all_pkmn_list = get_all_pokemon_list()
            updated = 0
            with st.spinner(f"Refreshing prices for {owned_count} Pokémon..."):
                for pid, entry in list(st.session_state.binder.items()):
                    pkmn = next((p for p in all_pkmn_list if str(p['id']) == pid), None)
                    if not pkmn:
                        continue
                    cards, _ = get_tcg_cards(pkmn['name'], top_n=20, api_key=api_key)
                    if not cards:
                        continue
                    match = next(
                        (c for c in cards
                         if c['name'] == entry.get('card_name') and c['set'] == entry.get('card_set')),
                        None
                    )
                    if match:
                        old_price = entry.get('card_value', 0)
                        new_price = match['price']
                        if old_price != new_price:
                            st.session_state.binder[pid]['old_price'] = old_price
                            st.session_state.binder[pid]['card_value'] = new_price
                            st.session_state.binder[pid]['last_price_update'] = datetime.now().isoformat()
                            updated += 1
            if updated:
                st.session_state.binder_dirty = True
                st.success(f"Updated prices for {updated} cards.")
                st.rerun()
            else:
                st.info("All prices already up to date.")
    with action_col2:
        # Export JSON
        if owned_count > 0:
            binder_json = json.dumps(st.session_state.binder, indent=2)
            st.download_button("📥 Export JSON", binder_json, "binder_export.json", "application/json", use_container_width=True)
        else:
            st.button("📥 Export JSON", disabled=True, use_container_width=True)
    with action_col3:
        # Export CSV
        if owned_count > 0:
            all_pkmn_list = get_all_pokemon_list()
            pkmn_lookup = {str(p['id']): p['name'] for p in all_pkmn_list}
            csv_buf = io.StringIO()
            writer = csv.writer(csv_buf)
            writer.writerow(["Pokedex #", "Pokemon", "Card Name", "Set", "Value", "Condition", "Date Added"])
            for pid, entry in sorted(st.session_state.binder.items(), key=lambda x: int(x[0])):
                writer.writerow([
                    pid, pkmn_lookup.get(pid, '?'), entry.get('card_name', ''),
                    entry.get('card_set', ''), f"{entry.get('card_value', 0):.2f}",
                    entry.get('condition', 'NM'), entry.get('date_added', '')
                ])
            st.download_button("📥 Export CSV", csv_buf.getvalue(), "binder_export.csv", "text/csv", use_container_width=True)
        else:
            st.button("📥 Export CSV", disabled=True, use_container_width=True)
    with action_col4:
        # Print button
        st.markdown(
            '<button onclick="window.print()" style="width:100%;padding:0.5rem;border:1px solid #1e1e38;'
            'border-radius:6px;background:#0f0f1a;color:#e8e8f0;cursor:pointer;font-size:0.82rem;'
            'font-family:Sora,sans-serif;transition:all 0.2s ease;"'
            ' onmouseover="this.style.borderColor=\'#ff6b35\';this.style.color=\'#ff6b35\';this.style.boxShadow=\'0 0 20px #ff6b3522\'"'
            ' onmouseout="this.style.borderColor=\'#1e1e38\';this.style.color=\'#e8e8f0\';this.style.boxShadow=\'none\'"'
            '>🖨️ Print Binder</button>',
            unsafe_allow_html=True
        )

    # Import
    with st.expander("📤 Import Binder Data"):
        uploaded = st.file_uploader("Upload JSON or CSV", type=["json", "csv"], key="binder_import")
        if uploaded:
            try:
                if uploaded.name.endswith('.json'):
                    imported = json.loads(uploaded.read().decode('utf-8'))
                    if isinstance(imported, dict):
                        merge_col1, merge_col2 = st.columns(2)
                        with merge_col1:
                            if st.button("🔄 Merge (keep existing)", key="import_merge"):
                                for k, v in imported.items():
                                    if k not in st.session_state.binder:
                                        st.session_state.binder[k] = v
                                st.session_state.binder_dirty = True
                                st.success(f"Merged {len(imported)} entries.")
                                st.rerun()
                        with merge_col2:
                            if st.button("⚠️ Replace all", key="import_replace"):
                                st.session_state.binder = imported
                                st.session_state.binder_dirty = True
                                st.success(f"Replaced with {len(imported)} entries.")
                                st.rerun()
                    else:
                        st.error("Invalid JSON format — expected object with Pokédex IDs as keys.")
                elif uploaded.name.endswith('.csv'):
                    content = uploaded.read().decode('utf-8')
                    reader = csv.DictReader(io.StringIO(content))
                    imported = {}
                    for row in reader:
                        pid = row.get('Pokedex #', '').strip()
                        if pid:
                            imported[pid] = {
                                "card_name": row.get('Card Name', ''),
                                "card_set": row.get('Set', ''),
                                "card_value": float(row.get('Value', 0)),
                                "condition": row.get('Condition', 'NM'),
                                "date_added": row.get('Date Added', datetime.now().isoformat()),
                            }
                    if imported:
                        merge_col1, merge_col2 = st.columns(2)
                        with merge_col1:
                            if st.button("🔄 Merge (keep existing)", key="import_csv_merge"):
                                for k, v in imported.items():
                                    if k not in st.session_state.binder:
                                        st.session_state.binder[k] = v
                                st.session_state.binder_dirty = True
                                st.success(f"Merged {len(imported)} entries.")
                                st.rerun()
                        with merge_col2:
                            if st.button("⚠️ Replace all", key="import_csv_replace"):
                                st.session_state.binder = imported
                                st.session_state.binder_dirty = True
                                st.success(f"Replaced with {len(imported)} entries.")
                                st.rerun()
                    else:
                        st.warning("No valid rows found in CSV.")
            except Exception as e:
                st.error(f"Import error: {e}")

    # Portfolio chart
    if owned_count > 0:
        with st.expander("📊 Portfolio Breakdown by Generation"):
            gen_values = {}
            gen_counts = {}
            for gen_name, (lo, hi) in GENERATIONS.items():
                vals = [v.get('card_value', 0) for pid, v in binder.items() if lo <= int(pid) <= hi]
                if vals:
                    gen_values[gen_name] = round(sum(vals), 2)
                    gen_counts[gen_name] = len(vals)
            if gen_values:
                chart_col1, chart_col2 = st.columns(2)
                with chart_col1:
                    st.caption("**Value by Generation ($)**")
                    st.bar_chart(gen_values)
                with chart_col2:
                    st.caption("**Cards Owned by Generation**")
                    st.bar_chart(gen_counts)

    st.divider()

    # Assignment panel placeholder
    assignment_container = st.container()

    # Filters
    f_col1, f_col2, f_col3, f_col4 = st.columns(4)
    with f_col1:
        binder_filter = st.selectbox("Show", ["All", "Owned", "Missing"], key="binder_filter_sel")
    with f_col2:
        binder_search = st.text_input("Search", placeholder="Search Pokémon name...", label_visibility="collapsed", key="binder_search_inp")
    with f_col3:
        gen_filter = st.selectbox("Generation", ["All"] + list(GENERATIONS.keys()), key="binder_gen_sel")
    with f_col4:
        sort_by = st.selectbox("Sort by", ["Pokédex #", "Value ↓", "Value ↑", "Name A→Z", "Recently Added"], key="binder_sort_sel")

    # Load and filter
    all_pokemon = get_all_pokemon_list()
    filtered = all_pokemon

    if gen_filter != "All":
        lo, hi = GENERATIONS[gen_filter]
        filtered = [p for p in filtered if lo <= p['id'] <= hi]
    if binder_search:
        filtered = [p for p in filtered if binder_search.lower() in p['name'].lower()]
    if binder_filter == "Owned":
        filtered = [p for p in filtered if str(p['id']) in binder]
    elif binder_filter == "Missing":
        filtered = [p for p in filtered if str(p['id']) not in binder]

    # Sort
    if sort_by == "Value ↓":
        filtered = sorted(filtered, key=lambda p: binder.get(str(p['id']), {}).get('card_value', 0), reverse=True)
    elif sort_by == "Value ↑":
        filtered = sorted(filtered, key=lambda p: binder.get(str(p['id']), {}).get('card_value', 0))
    elif sort_by == "Name A→Z":
        filtered = sorted(filtered, key=lambda p: p['name'])
    elif sort_by == "Recently Added":
        filtered = sorted(filtered, key=lambda p: binder.get(str(p['id']), {}).get('date_added', ''), reverse=True)

    # Pagination
    PER_PAGE = 50
    GRID_COLS = 5
    total_pages = max(1, (len(filtered) + PER_PAGE - 1) // PER_PAGE)
    if st.session_state.binder_page >= total_pages:
        st.session_state.binder_page = 0

    page_start = st.session_state.binder_page * PER_PAGE
    page_pokemon = filtered[page_start:page_start + PER_PAGE]

    p_col1, p_col2, p_col3 = st.columns([1, 3, 1])
    with p_col1:
        if st.button("← Prev", disabled=st.session_state.binder_page == 0, key="binder_prev_top"):
            st.session_state.binder_page -= 1
            st.rerun()
    with p_col2:
        st.caption(f"Page {st.session_state.binder_page + 1} of {total_pages}  ·  {len(filtered)} Pokémon shown")
    with p_col3:
        if st.button("Next →", disabled=st.session_state.binder_page >= total_pages - 1, key="binder_next_top"):
            st.session_state.binder_page += 1
            st.rerun()

    # Grid
    for row_start in range(0, len(page_pokemon), GRID_COLS):
        row = page_pokemon[row_start:row_start + GRID_COLS]
        grid_cols = st.columns(GRID_COLS)
        for col_idx, pkmn in enumerate(row):
            with grid_cols[col_idx]:
                pid = str(pkmn['id'])
                sprite_url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{pkmn['id']}.png"
                st.image(sprite_url, width=72)
                in_binder = pid in binder
                entry = binder.get(pid, {})
                st.caption(f"#{pkmn['id']:04d} {pkmn['name']}")
                if in_binder:
                    cond = entry.get('condition', 'NM')
                    cond_color = CONDITION_COLORS.get(cond, '#888')
                    old_price = entry.get('old_price')
                    cur_price = entry.get('card_value', 0)
                    price_str = f"**${cur_price:.2f}**"
                    if old_price is not None and old_price != cur_price:
                        delta = cur_price - old_price
                        arrow = "▲" if delta > 0 else "▼"
                        color = "green" if delta > 0 else "red"
                        price_str += f' <span style="color:{color};font-size:0.75em">{arrow}${abs(delta):.2f}</span>'
                    st.markdown(f'✅ {price_str}', unsafe_allow_html=True)
                    st.markdown(
                        f'<span style="background:{cond_color};color:white;padding:1px 6px;border-radius:8px;font-size:0.7em">{cond}</span>',
                        unsafe_allow_html=True
                    )
                    st.caption(entry.get('card_name', ''))
                if st.button("✏️" if in_binder else "＋", key=f"binder_btn_{pid}", use_container_width=True):
                    st.session_state.binder_active = pkmn['id']

    # Pagination bottom
    pb_col1, pb_col2, pb_col3 = st.columns([1, 3, 1])
    with pb_col1:
        if st.button("← Prev", disabled=st.session_state.binder_page == 0, key="binder_prev_bot"):
            st.session_state.binder_page -= 1
            st.rerun()
    with pb_col3:
        if st.button("Next →", disabled=st.session_state.binder_page >= total_pages - 1, key="binder_next_bot"):
            st.session_state.binder_page += 1
            st.rerun()

    # --- Card Assignment Panel ---
    with assignment_container:
        if st.session_state.binder_active:
            active_id = st.session_state.binder_active
            pkmn_data = next((p for p in all_pokemon if p['id'] == active_id), None)
            if pkmn_data:
                pid = str(active_id)
                existing = binder.get(pid, {})
                sprite_url = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{active_id}.png"

                assign_col1, assign_col2 = st.columns([1, 5])
                with assign_col1:
                    st.image(sprite_url, width=80)
                with assign_col2:
                    st.subheader(f"#{active_id:04d} {pkmn_data['name']}")
                    if existing:
                        st.caption(f"Currently: {existing.get('card_name', '?')} · {existing.get('card_set', '?')} · ${existing.get('card_value', 0):.2f}")

                with st.spinner(f"Loading cards for {pkmn_data['name']}..."):
                    tcg_cards, _ = get_tcg_cards(pkmn_data['name'], top_n=20, api_key=api_key)

                if tcg_cards:
                    st.markdown("**Pick a card from TCGplayer data:**")
                    pick_cols = st.columns(min(len(tcg_cards), 3))
                    for cidx, card in enumerate(tcg_cards):
                        with pick_cols[cidx % 3]:
                            if card['image']:
                                st.image(card['image'], width=80)
                            st.caption(f"{card['name']}")
                            st.caption(f"{card['set']}")
                            st.write(f"**${card['price']:.2f}**")
                            if st.button("Select", key=f"pick_{active_id}_{cidx}"):
                                st.session_state.binder[pid] = {
                                    "card_name": card['name'],
                                    "card_set": card['set'],
                                    "card_value": card['price'],
                                    "card_image": card['image'],
                                    "condition": "NM",
                                    "date_added": datetime.now().isoformat(),
                                }
                                st.session_state.binder_dirty = True
                                st.session_state.binder_active = None
                                st.rerun()
                else:
                    st.caption("No TCGplayer data found — use manual entry below.")

                with st.expander("Manual entry / override"):
                    cond_options = ["NM", "LP", "MP", "HP", "Damaged"]
                    cond_default = existing.get('condition', 'NM')
                    cond_idx = cond_options.index(cond_default) if cond_default in cond_options else 0
                    condition_sel = st.selectbox("Condition", cond_options, index=cond_idx, key=f"cond_{active_id}")

                    m_col1, m_col2, m_col3 = st.columns(3)
                    with m_col1:
                        card_name_in = st.text_input("Card name", value=existing.get('card_name', ''), key=f"mn_{active_id}")
                    with m_col2:
                        card_set_in = st.text_input("Set", value=existing.get('card_set', ''), key=f"ms_{active_id}")
                    with m_col3:
                        card_val_in = st.number_input("Value ($)", value=float(existing.get('card_value', 0.0)), min_value=0.0, step=0.01, key=f"mv_{active_id}")

                    save_c, remove_c, cancel_c = st.columns(3)
                    with save_c:
                        if st.button("💾 Save", key=f"save_{active_id}"):
                            st.session_state.binder[pid] = {
                                "card_name": card_name_in,
                                "card_set": card_set_in,
                                "card_value": card_val_in,
                                "card_image": existing.get('card_image', ''),
                                "condition": condition_sel,
                                "date_added": existing.get('date_added', datetime.now().isoformat()),
                            }
                            st.session_state.binder_dirty = True
                            st.session_state.binder_active = None
                            st.rerun()
                    with remove_c:
                        if pid in binder:
                            if st.button("🗑️ Remove", key=f"remove_{active_id}"):
                                del st.session_state.binder[pid]
                                st.session_state.binder_dirty = True
                                st.session_state.binder_active = None
                                st.rerun()
                    with cancel_c:
                        if st.button("✖ Cancel", key=f"cancel_{active_id}"):
                            st.session_state.binder_active = None
                            st.rerun()

                st.divider()

    # --- Set Completion Tracker ---
    st.subheader("🗂️ Set Completion Tracker")
    sets_list = get_tcg_sets(api_key=api_key)
    if sets_list:
        set_options = {f"{s['name']} ({s.get('releaseDate', '')[:4]})": s['id'] for s in sets_list}
        selected_set_label = st.selectbox("Pick a set", list(set_options.keys()), key="set_tracker_sel")
        selected_set_id = set_options[selected_set_label]

        with st.spinner("Loading set cards..."):
            set_cards = get_set_cards(selected_set_id, api_key=api_key)

        if set_cards:
            owned_in_set = [
                c for c in set_cards
                if any(
                    e.get('card_name') == c.get('name') and e.get('card_set') == c.get('set', {}).get('name')
                    for e in binder.values()
                )
            ]
            total_in_set = len(set_cards)
            owned_in_set_count = len(owned_in_set)
            st.caption(f"Owned: {owned_in_set_count} / {total_in_set}")
            st.progress(owned_in_set_count / total_in_set if total_in_set > 0 else 0)

            set_grid_cols = st.columns(6)
            for sidx, card in enumerate(set_cards):
                card_name = card.get('name', '')
                card_set_name = card.get('set', {}).get('name', '')
                is_owned = any(
                    e.get('card_name') == card_name and e.get('card_set') == card_set_name
                    for e in binder.values()
                )
                with set_grid_cols[sidx % 6]:
                    img = card.get('images', {}).get('small', '')
                    if img:
                        st.image(img, use_container_width=True)
                    st.caption(f"{'✅' if is_owned else '☐'} {card.get('number', '')} {card_name}")
        else:
            st.caption("No cards found for this set.")
    else:
        st.caption("Could not load sets from pokemontcg.io.")

# ============================================================
# TOP 1025 TAB
# ============================================================
with main_tab_top:
    st.subheader("💎 Most Valuable Card per Pokémon")
    st.caption("The single highest TCGplayer market price card for each of the 1025 Pokémon.")

    api_key_top = st.secrets.get("POKEMONTCG_API_KEY", "")

    if "top1025_data" not in st.session_state:
        st.session_state.top1025_data = None
    if "top1025_page" not in st.session_state:
        st.session_state.top1025_page = 0

    _top1025_raw = localS.getItem("top1025_cache")
    if st.session_state.top1025_data is None and _top1025_raw:
        try:
            st.session_state.top1025_data = json.loads(_top1025_raw)
        except (json.JSONDecodeError, TypeError):
            pass

    if st.session_state.top1025_data is None:
        st.info(
            "⏱️ **First load fetches all 1025 Pokémon from TCGplayer** — takes ~20-30 seconds. "
            "Results are saved in your browser so you only wait once."
        )
        load_col, _ = st.columns([1, 3])
        with load_col:
            if st.button("🚀 Load Top 1025", type="primary", use_container_width=True):
                all_pkmn = get_all_pokemon_list()
                total = len(all_pkmn)
                results = []
                prog = st.progress(0)
                status_txt = st.empty()
                done_count = 0

                def fetch_one(pkmn):
                    cards, _ = get_tcg_cards(pkmn['name'], top_n=1, api_key=api_key_top)
                    if cards:
                        return {
                            "id": pkmn['id'],
                            "pokemon": pkmn['name'],
                            "card_name": cards[0]['name'],
                            "set": cards[0]['set'],
                            "rarity": cards[0]['rarity'],
                            "price": cards[0]['price'],
                            "image": cards[0]['image'],
                            "url": cards[0]['url'],
                        }
                    return None

                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = {executor.submit(fetch_one, p): p for p in all_pkmn}
                    for future in as_completed(futures):
                        done_count += 1
                        pkmn = futures[future]
                        status_txt.caption(f"Fetched {done_count}/{total} — {pkmn['name']}")
                        prog.progress(done_count / total)
                        result = future.result()
                        if result:
                            results.append(result)

                status_txt.empty()
                prog.empty()
                results.sort(key=lambda x: x['price'], reverse=True)
                for i, r in enumerate(results):
                    r['rank'] = i + 1
                st.session_state.top1025_data = results
                st.session_state.top1025_page = 0
                localS.setItem("top1025_cache", json.dumps(results))
                st.rerun()
    else:
        data = st.session_state.top1025_data

        # Controls — added gen filter
        ctrl_col1, ctrl_col2, ctrl_col3, ctrl_col4 = st.columns([2, 1, 1, 1])
        with ctrl_col1:
            top_search = st.text_input("Filter", placeholder="Search Pokémon name...", label_visibility="collapsed", key="top1025_search")
        with ctrl_col2:
            top_gen_filter = st.selectbox("Gen", ["All"] + list(GENERATIONS.keys()), key="top1025_gen_sel", label_visibility="collapsed")
        with ctrl_col3:
            top_sort = st.selectbox("Sort", ["Price ↓", "Price ↑", "Pokédex #"], key="top1025_sort_sel", label_visibility="collapsed")
        with ctrl_col4:
            if st.button("🔄 Reload", use_container_width=True):
                st.session_state.top1025_data = None
                st.session_state.top1025_page = 0
                localS.deleteItem("top1025_cache")
                st.rerun()

        # Filter + sort
        display_data = data
        if top_search:
            display_data = [r for r in display_data if top_search.lower() in r['pokemon'].lower()]
        if top_gen_filter != "All":
            lo, hi = GENERATIONS[top_gen_filter]
            display_data = [r for r in display_data if lo <= r['id'] <= hi]
        if top_sort == "Price ↓":
            display_data = sorted(display_data, key=lambda x: x['price'], reverse=True)
        elif top_sort == "Price ↑":
            display_data = sorted(display_data, key=lambda x: x['price'])
        elif top_sort == "Pokédex #":
            display_data = sorted(display_data, key=lambda x: x['id'])

        total_value_top = sum(r['price'] for r in display_data)
        t_col1, t_col2 = st.columns(2)
        with t_col1:
            st.metric("Pokémon with pricing", len(display_data))
        with t_col2:
            st.metric("Combined value", f"${total_value_top:,.2f}")

        # Pagination
        TOP_PER_PAGE = 50
        TOP_COLS = 5
        total_top_pages = max(1, (len(display_data) + TOP_PER_PAGE - 1) // TOP_PER_PAGE)
        if st.session_state.top1025_page >= total_top_pages:
            st.session_state.top1025_page = 0

        tp_col1, tp_col2, tp_col3 = st.columns([1, 3, 1])
        with tp_col1:
            if st.button("← Prev", disabled=st.session_state.top1025_page == 0, key="top_prev"):
                st.session_state.top1025_page -= 1
                st.rerun()
        with tp_col2:
            st.caption(f"Page {st.session_state.top1025_page + 1} of {total_top_pages}  ·  {len(display_data)} Pokémon")
        with tp_col3:
            if st.button("Next →", disabled=st.session_state.top1025_page >= total_top_pages - 1, key="top_next"):
                st.session_state.top1025_page += 1
                st.rerun()

        page_start_top = st.session_state.top1025_page * TOP_PER_PAGE
        page_data = display_data[page_start_top:page_start_top + TOP_PER_PAGE]

        # Grid
        binder = st.session_state.binder
        for row_start in range(0, len(page_data), TOP_COLS):
            row = page_data[row_start:row_start + TOP_COLS]
            cols = st.columns(TOP_COLS)
            for col_idx, item in enumerate(row):
                with cols[col_idx]:
                    if item['image']:
                        st.image(item['image'], use_container_width=True)
                    rank_label = f"#{item['rank']}" if top_sort == "Price ↓" else f"#{item['id']:04d}"
                    st.caption(f"{rank_label} **{item['pokemon']}**")
                    st.write(f"**${item['price']:.2f}**")
                    st.caption(item['set'])
                    pid = str(item['id'])
                    if pid in binder:
                        st.caption("✅ In binder")
                    else:
                        if st.button("📒 Add", key=f"top_add_{item['id']}", use_container_width=True):
                            st.session_state.binder[pid] = {
                                "card_name": item['card_name'],
                                "card_set": item['set'],
                                "card_value": item['price'],
                                "card_image": item['image'],
                                "condition": "NM",
                                "date_added": datetime.now().isoformat(),
                            }
                            st.session_state.binder_dirty = True
                            st.rerun()
                    st.link_button("TCGplayer ↗", item['url'], use_container_width=True)

# ============================================================
# COMPARE TAB
# ============================================================
with main_tab_compare:
    st.subheader("⚖️ Compare Pokémon")
    st.caption("Select up to 3 Pokémon to compare stats and most valuable cards side-by-side.")

    all_pkmn_names = get_all_pokemon_list()
    name_to_id = {p['name']: p['id'] for p in all_pkmn_names}

    compare_cols = st.columns(3)
    compare_pokemon = []
    for i in range(3):
        with compare_cols[i]:
            pick = st.selectbox(
                f"Pokémon {i+1}",
                ["—"] + [p['name'] for p in all_pkmn_names],
                key=f"compare_pick_{i}"
            )
            if pick != "—":
                compare_pokemon.append(pick)

    if compare_pokemon:
        st.divider()
        comp_cols = st.columns(len(compare_pokemon))
        api_key_cmp = st.secrets.get("POKEMONTCG_API_KEY", "")

        for ci, pname in enumerate(compare_pokemon):
            with comp_cols[ci]:
                pdata = fetch_pokemon_data(name_to_id[pname])
                if pdata and not pdata.get('error'):
                    if pdata['sprite']:
                        st.image(pdata['sprite'], width=150)
                    primary = pdata['types'][0]
                    accent = TYPE_COLORS.get(primary, '#888')
                    st.markdown(
                        f'<h3 style="font-family:\'Chakra Petch\',sans-serif; color:{accent}; margin-bottom:0.3rem;">'
                        f'{pdata["name"]} '
                        f'<span style="color:#6e6e8a; font-size:0.55em; font-weight:400">#{pdata["id"]:04d}</span></h3>',
                        unsafe_allow_html=True
                    )
                    st.markdown("".join(type_badge(t) for t in pdata['types']), unsafe_allow_html=True)

                    st.markdown("**Stats**")
                    for stat_key, stat_label in STAT_NAMES.items():
                        val = pdata['stats'].get(stat_key, 0)
                        st.caption(f"{stat_label}: **{val}**")
                        st.progress(min(val / 255, 1.0))

                    bst = sum(pdata['stats'].values())
                    st.metric("Base Stat Total", bst)

                    # Top card
                    cards, _ = get_tcg_cards(pdata['name'], top_n=1, api_key=api_key_cmp)
                    if cards:
                        st.divider()
                        st.caption("**Most Valuable Card**")
                        if cards[0]['image']:
                            st.image(cards[0]['image'], use_container_width=True)
                        st.write(f"**${cards[0]['price']:.2f}**")
                        st.caption(f"{cards[0]['name']} · {cards[0]['set']}")

# ============================================================
# WISHLIST TAB
# ============================================================
with main_tab_wishlist:
    st.subheader("💫 Wishlist")
    st.caption("Track Pokémon cards you want. Set a target price and see current TCGplayer value.")

    wishlist = st.session_state.wishlist

    # Add to wishlist
    with st.expander("➕ Add to Wishlist", expanded=len(wishlist) == 0):
        all_pkmn_w = get_all_pokemon_list()
        w_col1, w_col2 = st.columns([3, 1])
        with w_col1:
            wish_pick = st.selectbox("Pokémon", [p['name'] for p in all_pkmn_w], key="wish_pick_sel")
        with w_col2:
            wish_target = st.number_input("Target price ($)", min_value=0.0, step=0.50, value=10.0, key="wish_target_in")
        if st.button("Add to Wishlist", use_container_width=True):
            wish_id = str(next(p['id'] for p in all_pkmn_w if p['name'] == wish_pick))
            st.session_state.wishlist[wish_id] = {
                "name": wish_pick,
                "target_price": wish_target,
                "date_added": datetime.now().isoformat(),
            }
            st.session_state.wishlist_dirty = True
            st.rerun()

    if not wishlist:
        st.info("Wishlist empty. Add Pokémon above.")
    else:
        st.caption(f"{len(wishlist)} Pokémon on wishlist")
        api_key_w = st.secrets.get("POKEMONTCG_API_KEY", "")
        wish_cols = st.columns(min(len(wishlist), 4))
        for widx, (wid, wentry) in enumerate(wishlist.items()):
            with wish_cols[widx % min(len(wishlist), 4)]:
                sprite = f"https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/{wid}.png"
                st.image(sprite, width=72)
                st.markdown(f"**{wentry['name']}**")
                st.caption(f"Target: ${wentry['target_price']:.2f}")

                # Check current price
                cards, _ = get_tcg_cards(wentry['name'], top_n=1, api_key=api_key_w)
                if cards:
                    cur = cards[0]['price']
                    if cur <= wentry['target_price']:
                        st.success(f"🎯 ${cur:.2f} — below target!")
                    else:
                        st.write(f"Current: ${cur:.2f}")
                else:
                    st.caption("No price data")

                if st.button("🗑️", key=f"wish_rm_{wid}"):
                    del st.session_state.wishlist[wid]
                    st.session_state.wishlist_dirty = True
                    st.rerun()

# ============================================================
# STATS TAB
# ============================================================
with main_tab_stats:
    st.subheader("📊 Collection Statistics")
    binder = st.session_state.binder

    if not binder:
        st.info("No cards in your binder yet. Add some in the Pokédex Binder tab!")
    else:
        values = [v.get('card_value', 0) for v in binder.values()]
        conditions = [v.get('condition', 'NM') for v in binder.values()]
        rarities = []
        all_pkmn_s = get_all_pokemon_list()
        pkmn_lookup_s = {str(p['id']): p for p in all_pkmn_s}

        # Overview metrics
        m_col1, m_col2, m_col3, m_col4 = st.columns(4)
        with m_col1:
            st.metric("Total Cards", len(binder))
        with m_col2:
            st.metric("Total Value", f"${sum(values):,.2f}")
        with m_col3:
            st.metric("Average Value", f"${sum(values)/len(values):,.2f}" if values else "$0.00")
        with m_col4:
            st.metric("Completion", f"{len(binder)/1025*100:.1f}%")

        st.divider()

        # Most / Least valuable
        sorted_entries = sorted(binder.items(), key=lambda x: x[1].get('card_value', 0), reverse=True)

        val_col1, val_col2 = st.columns(2)
        with val_col1:
            st.markdown("**💰 Most Valuable**")
            for pid, entry in sorted_entries[:5]:
                pname = pkmn_lookup_s.get(pid, {}).get('name', f'#{pid}')
                st.caption(f"#{int(pid):04d} {pname} — **${entry.get('card_value', 0):.2f}** ({entry.get('card_name', '')})")
        with val_col2:
            st.markdown("**🪙 Least Valuable**")
            for pid, entry in sorted_entries[-5:]:
                pname = pkmn_lookup_s.get(pid, {}).get('name', f'#{pid}')
                st.caption(f"#{int(pid):04d} {pname} — **${entry.get('card_value', 0):.2f}** ({entry.get('card_name', '')})")

        st.divider()

        # Condition breakdown
        cond_col1, cond_col2 = st.columns(2)
        with cond_col1:
            st.markdown("**Card Condition Breakdown**")
            cond_counts = {}
            for c in conditions:
                cond_counts[c] = cond_counts.get(c, 0) + 1
            st.bar_chart(cond_counts)
        with cond_col2:
            st.markdown("**Value by Generation**")
            gen_val = {}
            for pid, entry in binder.items():
                pid_int = int(pid)
                for gen_name, (lo, hi) in GENERATIONS.items():
                    if lo <= pid_int <= hi:
                        gen_val[gen_name] = gen_val.get(gen_name, 0) + entry.get('card_value', 0)
                        break
            if gen_val:
                st.bar_chart({k: round(v, 2) for k, v in gen_val.items()})

        st.divider()

        # Type distribution
        st.markdown("**Type Distribution of Collected Pokémon**")
        type_counts = {}
        for pid in binder:
            pkmn_info = pkmn_lookup_s.get(pid)
            if pkmn_info:
                pdata = fetch_pokemon_data(int(pid))
                if pdata and not pdata.get('error'):
                    for t in pdata.get('types', []):
                        type_counts[t] = type_counts.get(t, 0) + 1
        if type_counts:
            st.bar_chart(dict(sorted(type_counts.items(), key=lambda x: x[1], reverse=True)))

        st.divider()

        # Recently added
        st.markdown("**🕐 Recently Added**")
        recent = sorted(binder.items(), key=lambda x: x[1].get('date_added', ''), reverse=True)[:10]
        for pid, entry in recent:
            pname = pkmn_lookup_s.get(pid, {}).get('name', f'#{pid}')
            date_str = entry.get('date_added', '')[:10]
            st.caption(f"#{int(pid):04d} {pname} — {entry.get('card_name', '')} · ${entry.get('card_value', 0):.2f} · {date_str}")
