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

def fetch_random_pokemon(max_id):
    """Fetches a random Pokémon, its types, and its official sprite image."""
    random_id = random.randint(1, max_id)
    api_url = f"https://pokeapi.co/api/v2/pokemon/{random_id}"
    
    try:
        response = requests.get(api_url)
        if response.status_code == 200:
            data = response.json()
            
            pokemon_name = data['species']['name'].replace('-', ' ').title()
            types = [t['type']['name'].capitalize() for t in data['types']]
            # Get the official artwork sprite
            sprite_url = data['sprites']['other']['official-artwork']['front_default']
            
            return {
                "name": pokemon_name,
                "id": random_id,
                "types": "/".join(types),
                "sprite": sprite_url
            }
    except requests.exceptions.RequestException:
        return None

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
    """
    Template for eBay API integration to check actual sold prices.
    You will need to insert your eBay OAuth token and App ID here.
    """
    # 1. You will need an OAuth access token from your eBay Developer Account
    oauth_token = "YOUR_EBAY_OAUTH_TOKEN_HERE" 
    
    # 2. Setup the headers for the eBay Browse API
    headers = {
        "Authorization": f"Bearer {oauth_token}",
        "Content-Type": "application/json",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US"
    }
    
    # 3. Formulate the search query (e.g., "Charizard Base Set PSA")
    search_query = f"{card_name} {set_name} Pokemon"
    
    # 4. Make the request to the eBay API (Endpoint example for searching items)
    # url = f"https://api.ebay.com/buy/browse/v1/item_summary/search?q={search_query}&filter=itemEndDate:[..now]"
    # response = requests.get(url, headers=headers)
    # Parse status codes and JSON response here to find the average sold price.
    
    # Returning a placeholder string until credentials are added
    return "eBay API integration pending OAuth setup"

# --- Streamlit UI ---

st.set_page_config(page_title="Pokémon Card Tracker", layout="wide")

st.title("⚡ Pokémon Card Market Dashboard")
st.write("Generate a random Pokémon and check its top TCGplayer market prices.")

# Session state keeps the Pokémon on the screen when we click other buttons
if 'current_pokemon' not in st.session_state:
    st.session_state.current_pokemon = None

if st.button("Catch a Random Pokémon", type="primary"):
    with st.spinner("Searching the tall grass..."):
        total_pokemon = get_total_pokemon()
        st.session_state.current_pokemon = fetch_random_pokemon(total_pokemon)

if st.session_state.current_pokemon:
    pokemon = st.session_state.current_pokemon
    
    # Display the Pokémon using columns
    col1, col2 = st.columns([1, 3])
    with col1:
        if pokemon['sprite']:
            st.image(pokemon['sprite'], width=200)
    with col2:
        st.header(f"{pokemon['name']} (# {pokemon['id']})")
        st.subheader(f"Type: {pokemon['types']}")
        
    st.divider()
    
    st.subheader(f"Top Valuable Cards for {pokemon['name']}")
    with st.spinner("Pulling data from TCGplayer..."):
        top_cards = get_tcg_cards(pokemon['name'])
        
        if not top_cards:
            st.warning("No pricing data found for this Pokémon.")
        else:
            # Create a grid of cards
            card_columns = st.columns(len(top_cards))
            
            for idx, card in enumerate(top_cards):
                with card_columns[idx]:
                    if card['image']:
                        st.image(card['image'], use_container_width=True)
                    st.write(f"**{card['set']}**")
                    st.write(f"TCG Market: **${card['price']:.2f}**")
                    
                    # eBay Integration Call (Placeholder)
                    ebay_status = check_ebay_sold_listings(card['name'], card['set'])
                    st.caption(f"*eBay:* {ebay_status}")
                    
                    st.link_button("View on TCGplayer", card['url'])
