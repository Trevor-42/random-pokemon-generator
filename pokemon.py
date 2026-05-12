import streamlit as st
import random
import requests

# --- API Functions ---

def get_total_pokemon():
    """Fetches the current total number of Pokémon species."""
    try:
        response = requests.get("https://pokeapi.co/api/v2/pokemon-species/")
        if response.status_code == 200:
            return response.json()['count']
    except requests.exceptions.RequestException:
        pass
    return 1025

def fetch_pokemon_data(identifier):
    """Fetches a Pokémon by ID (number) or Name (string)."""
    clean_id = str(identifier).strip().lower().replace(" ", "-")
    api_url = f"https://pokeapi.co/api/v2/pokemon/{clean_id}"
    
    try:
        response = requests.get(api_url)
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

def get_tcg_cards(pokemon_name, top_n=5):
    """Fetches top English cards and their images from the Pokémon TCG API."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    api_url = "https://api.pokemontcg.io/v2/cards"
    params = {"q": f'name:"{pokemon_name}"'}
    
    try:
        response = requests.get(api_url, headers=headers, params=params)
        if response.status_code != 200:
            return None

        cards = response.json().get('data', [])
        card_prices = []
        
        for card in cards:
            tcgplayer = card.get('tcgplayer', {})
            prices = tcgplayer.get('prices', {})
            
            highest_price = 0
            for price_type, price_data in prices.items():
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

def check_ebay_sold_listings(card_name, set_name):
    """Template for eBay API integration to check actual sold prices."""
    oauth_token = "YOUR_EBAY_OAUTH_TOKEN_HERE" 
    headers = {
        "Authorization": f"Bearer {oauth_token}",
        "Content-Type": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"
    }
    search_query = f"{card_name} {set_name} Pokemon"
    return "eBay API integration pending OAuth setup"

# --- Streamlit UI ---

st.set_page_config(page_title="Pokémon Card Tracker", layout="wide")

st.title("⚡ Pokémon Card Market Dashboard")
st.write("Search for a specific Pokémon or catch a random one to check its top TCGplayer market prices.")

if 'current_pokemon' not in st.session_state:
    st.session_state.current_pokemon = None

# --- Top Control Panel ---
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

# --- Display Results ---
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
                        
                        # --- THIS IS THE NEW SECTION ---
                        st.markdown(f"**{card['name']}**") # Adds the specific card name
                        st.caption(f"Set: {card['set']}")  # Makes the set name a bit smaller/cleaner
                        st.write(f"TCG Market: **${card['price']:.2f}**")
                        # -------------------------------
                        
                        ebay_status = check_ebay_sold_listings(card['name'], card['set'])
                        st.caption(f"*eBay:* {ebay_status}")
                        
                        st.link_button("View on TCGplayer", card['url'])
