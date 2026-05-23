import json
import streamlit as st
import random
import requests
import base64
from urllib.parse import urlencode
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

# --- eBay OAuth Config ---
EBAY_AUTH_URL = "https://auth.ebay.com/oauth2/authorize"
EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_SCOPES = "https://api.ebay.com/oauth/api_scope"
SHOW_EBAY = False

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

def type_badge(type_name):
    color = TYPE_COLORS.get(type_name, '#888888')
    return (f'<span style="background-color:{color}; color:white; padding:2px 10px; '
            f'border-radius:12px; font-weight:600; font-size:0.85em; margin-right:4px;">'
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
@media screen and (max-width: 640px) {
    [data-testid="stHorizontalBlock"] {
        flex-wrap: wrap;
    }
    [data-testid="stHorizontalBlock"] > [data-testid="column"] {
        width: 100% !important;
        flex: 1 1 100% !important;
        min-width: 100% !important;
    }
    [data-testid="stImage"] img {
        max-width: 160px !important;
    }
    h1 { font-size: 1.5rem !important; }
    h2 { font-size: 1.2rem !important; }
}
</style>
""", unsafe_allow_html=True)

st.title("⚡ Pokémon Card Market Dashboard")

# --- LocalStorage init (must be at top level, not inside tabs) ---
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

if st.session_state.get("binder_dirty"):
    localS.setItem("pokedex_binder", json.dumps(st.session_state.binder))
    st.session_state.binder_dirty = False

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

# --- URL param loading ---
_url_pokemon = st.query_params.get("pokemon")
if _url_pokemon and st.session_state.current_pokemon is None:
    with st.spinner("Loading Pokémon..."):
        st.session_state.current_pokemon = fetch_pokemon_data(_url_pokemon)

# --- Top-level tabs ---
main_tab_search, main_tab_binder = st.tabs(["🔍 Search & Card Market", "📒 Pokédex Binder"])

with main_tab_search:
    # --- Search Controls ---
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

    # --- Results ---
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
                        f'<h2 style="color:{accent_color}">{pokemon["name"]} '
                        f'<span style="color:#888; font-size:0.7em">#{pokemon["id"]}</span></h2>',
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

# --- Pokédex Binder Tab ---
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

    st.divider()

    # Assignment panel placeholder — filled after grid so binder_active is set
    assignment_container = st.container()

    # Filters
    f_col1, f_col2, f_col3 = st.columns(3)
    with f_col1:
        binder_filter = st.selectbox("Show", ["All", "Owned", "Missing"], key="binder_filter_sel")
    with f_col2:
        binder_search = st.text_input("Search", placeholder="Search Pokémon name...", label_visibility="collapsed", key="binder_search_inp")
    with f_col3:
        gen_filter = st.selectbox("Generation", ["All"] + list(GENERATIONS.keys()), key="binder_gen_sel")

    # Load and filter Pokémon list
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

    # Pagination
    PER_PAGE = 50
    GRID_COLS = 5
    total_pages = max(1, (len(filtered) + PER_PAGE - 1) // PER_PAGE)
    if st.session_state.binder_page >= total_pages:
        st.session_state.binder_page = 0

    page_start = st.session_state.binder_page * PER_PAGE
    page_pokemon = filtered[page_start:page_start + PER_PAGE]

    # Pagination controls (top)
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
                    st.markdown(f"✅ **${entry.get('card_value', 0):.2f}**")
                    st.caption(entry.get('card_name', ''))
                if st.button("✏️" if in_binder else "＋", key=f"binder_btn_{pid}", use_container_width=True):
                    st.session_state.binder_active = pkmn['id']

    # Pagination controls (bottom)
    pb_col1, pb_col2, pb_col3 = st.columns([1, 3, 1])
    with pb_col1:
        if st.button("← Prev", disabled=st.session_state.binder_page == 0, key="binder_prev_bot"):
            st.session_state.binder_page -= 1
            st.rerun()
    with pb_col3:
        if st.button("Next →", disabled=st.session_state.binder_page >= total_pages - 1, key="binder_next_bot"):
            st.session_state.binder_page += 1
            st.rerun()

    # --- Card Assignment Panel (rendered into container above grid) ---
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

                api_key = st.secrets.get("POKEMONTCG_API_KEY", "")
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
                                }
                                st.session_state.binder_dirty = True
                                st.session_state.binder_active = None
                                st.rerun()
                else:
                    st.caption("No TCGplayer data found — use manual entry below.")

                with st.expander("Manual entry / override"):
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
