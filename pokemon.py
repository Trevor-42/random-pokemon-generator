import random
import requests

def get_total_pokemon():
    """Fetches the current total number of Pokémon species."""
    try:
        response = requests.get("https://pokeapi.co/api/v2/pokemon-species/")
        if response.status_code == 200:
            return response.json()['count']
    except requests.exceptions.RequestException:
        pass
    return 1025

def get_top_cards(pokemon_name, top_n=5):
    """Fetches the top English cards for a given Pokémon based on TCGplayer market price, including URLs."""
    print(f"\nScanning TCGplayer data for the most expensive {pokemon_name} cards...")
    
    api_url = "https://api.pokemontcg.io/v2/cards"
    params = {"q": f'name:"{pokemon_name}"'}
    
    try:
        response = requests.get(api_url, params=params)
        if response.status_code == 200:
            cards = response.json().get('data', [])
            
            card_prices = []
            for card in cards:
                tcgplayer = card.get('tcgplayer', {})
                prices = tcgplayer.get('prices', {})
                
                # Extract the direct TCGplayer URL (defaulting to a message if missing)
                store_url = tcgplayer.get('url', 'No link available')
                
                if not prices:
                    continue
                    
                highest_price = 0
                for price_type, price_data in prices.items():
                    market_price = price_data.get('market', 0)
                    if market_price and market_price > highest_price:
                        highest_price = market_price
                        
                if highest_price > 0:
                    card_prices.append({
                        'name': card.get('name', pokemon_name),
                        'set': card.get('set', {}).get('name', 'Unknown Set'),
                        'price': highest_price,
                        'number': card.get('number', 'N/A'),
                        'url': store_url
                    })
            
            card_prices.sort(key=lambda x: x['price'], reverse=True)
            
            print(f"\n--- Top {top_n} Most Valuable English Cards for {pokemon_name} ---")
            if not card_prices:
                print("No pricing data found.")
            else:
                for i, card in enumerate(card_prices[:top_n], 1):
                    print(f"\n{i}. {card['name']} - {card['set']} (#{card['number']})")
                    print(f"   Price: ${card['price']:.2f}")
                    print(f"   Link:  {card['url']}")
            print("\n----------------------------------------------------------------")
            
        else:
            print("Error: Could not retrieve card data from the TCG API.")
            
    except requests.exceptions.RequestException as e:
        print(f"An error occurred fetching card data: {e}")

def fetch_random_pokemon(max_id):
    """Fetches a random Pokémon and returns its cleaned name."""
    random_id = random.randint(1, max_id)
    api_url = f"https://pokeapi.co/api/v2/pokemon/{random_id}"
    
    try:
        response = requests.get(api_url)
        
        if response.status_code == 200:
            data = response.json()
            
            pokemon_name = data['species']['name'].replace('-', ' ').title()
            types = [t['type']['name'].capitalize() for t in data['types']]
            types_str = "/".join(types)
            
            print("\n================================")
            print("✨ A WILD POKÉMON APPEARED! ✨")
            print("================================")
            print(f"Name:     {pokemon_name} (# {random_id})")
            print(f"Type:     {types_str}")
            print("================================\n")
            
            return pokemon_name
            
        else:
            print(f"Error: Could not retrieve data (Status Code: {response.status_code})")
            
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")
        
    return None

if __name__ == "__main__":
    print("Initializing Pokédex...")
    total_pokemon = get_total_pokemon()
    
    while True:
        pokemon_name = fetch_random_pokemon(total_pokemon)
        
        if pokemon_name:
            user_input = input("Press [C] to check top card prices, [ENTER] to catch another, or 'q' to quit: ").strip().lower()
