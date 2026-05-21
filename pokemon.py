import streamlit as st
import random
import requests
import base64
from urllib.parse import urlencode

# --- eBay OAuth Config ---
EBAY_AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SCOPES = "https://api.ebay.com/oauth/api_scope"

# --- Page Config (must be first) ---
st.set_page_config(page_title="Pokémon Card Tracker", layout="wide")

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

    # Try to refresh if we have a refresh token stored
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
                # Refresh failed — clear tokens and re-auth
                del st.session_state["ebay_access_token"]
                return None

    return st.session_state.get("ebay_access_token")

# --- Handle OAuth Callback (eBay redirects back with ?code=...) ---
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
            return {
                "name": pokemon_name,
                "id": data['id'],
                "types": "/".join(types),
                "sprite": sprite_url,
                "error": None
            }
        elif response.status_code == 404:
            return {"error": f"Could not find a Pokémon named '{identifier}'. Check your spelling!"}
        else:
            return {"error": "API Error. Please try again later."}
    except requests.exceptions.RequestException:
        return {"error": "Connection error to PokéAPI."}

@st.cache_data(ttl=3600)
def get_tcg_cards(pokemon_name, top_n=5):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        response = requests.get(
            "https://api.pokemontcg.io/v2/cards",
            headers=headers,
            params={"q": f'name:"{pokemon_name}"'},
        )
        if response.status_code != 200:
            return None

        cards = response.json().get('data', [])
        card_prices = []
        for card in cards:
            tcgplayer = card.get('tcgplayer', {})
            prices = tcgplayer.get('prices', {})
            highest_price = 0
            for price_data in prices.values():
                market_price = price_data.get('market')
                if market_price is not None and market_price > highest_price:
                    highest_price = market_price
            if highest_price > 0:
                card_prices.append({
                    'name': card.get('name', pokemon_name),
                    'set': card.get('set', {}).get('name', 'Unknown Set'),
                    'price': highest_price,
                    'image': card.get('images', {}).get('small', ''),
                    'url': tcgplayer.get('url', '#')
                })
        card_prices.sort(key=lambda x: x['price'], reverse=True)
        return card_prices[:top_n]
    except requests.exceptions.RequestException:
        return None

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

st.title("⚡ Pokémon Card Market Dashboard")
st.write("Search for a specific Pokémon or catch a random one to check its top TCGplayer market prices.")

# eBay connection banner
ebay_token = get_ebay_token()
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

if 'current_pokemon' not in st.session_state:
    st.session_state.current_pokemon = None

# --- Search Controls ---
col1, col2 = st.columns(2)
with col1:
    st.subheader("Surprise Me!")
    if st.button("Catch a Random Pokémon", type="primary", use_container_width=True):
        with st.spinner("Searching the tall grass..."):
            total_pokemon = get_total_pokemon()
            random_id = random.randint(1, total_pokemon)
            st.session_state.current_pokemon = fetch_pokemon_data(random_id)

with col2:
    st.subheader("Look Up Pokémon")
    with st.form("search_form"):
        search_query = st.text_input("Enter a Pokémon name (e.g., Charizard, Lugia):", label_visibility="collapsed", placeholder="Enter a Pokémon name...")
        submitted = st.form_submit_button("Search", use_container_width=True)
        if submitted and search_query:
            with st.spinner(f"Looking up {search_query}..."):
                st.session_state.current_pokemon = fetch_pokemon_data(search_query)

st.divider()

# --- Results ---
if st.session_state.current_pokemon:
    pokemon = st.session_state.current_pokemon

    if pokemon.get("error"):
        st.error(pokemon["error"])
    else:
        poke_col1, poke_col2 = st.columns([1, 3])
        with poke_col1:
            if pokemon['sprite']:
                st.image(pokemon['sprite'], width=200)
        with poke_col2:
            st.header(f"{pokemon['name']} (# {pokemon['id']})")
            st.subheader(f"Type: {pokemon['types']}")

        st.subheader(f"Top Valuable Cards for {pokemon['name']}")
        with st.spinner("Pulling data from TCGplayer..."):
            top_cards = get_tcg_cards(pokemon['name'])

            if not top_cards:
                st.warning("No pricing data found for this Pokémon.")
            else:
                card_columns = st.columns(len(top_cards))
                for idx, card in enumerate(top_cards):
                    with card_columns[idx]:
                        if card['image']:
                            st.image(card['image'], use_container_width=True)
                        st.markdown(f"**{card['name']}**")
                        st.caption(f"Set: {card['set']}")
                        st.write(f"TCG Market: **${card['price']:.2f}**")

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
