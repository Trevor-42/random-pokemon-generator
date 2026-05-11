import random
import requests

def get_total_pokemon():
    """Fetches the current total number of Pokémon species from the API."""
    try:
        response = requests.get("https://pokeapi.co/api/v2/pokemon-species/")
        if response.status_code == 200:
            return response.json()['count']
    except requests.exceptions.RequestException:
        pass
    return 1025 # Fallback number if the request fails

def fetch_random_pokemon(max_id):
    """Fetches and displays a random Pokémon."""
    random_id = random.randint(1, max_id)
    api_url = f"https://pokeapi.co/api/v2/pokemon/{random_id}"
    
    try:
        response = requests.get(api_url)
        
        if response.status_code == 200:
            data = response.json()
            
            pokemon_name = data['name'].capitalize()
            types = [t['type']['name'].capitalize() for t in data['types']]
            types_str = "/".join(types)
            
            # New Data: Height (in decimeters) and Weight (in hectograms)
            height_m = data['height'] / 10 
            weight_kg = data['weight'] / 10
            
            # New Data: Abilities
            abilities = [a['ability']['name'].replace('-', ' ').title() for a in data['abilities']]
            abilities_str = ", ".join(abilities)
            
            print("\n================================")
            print("✨ A WILD POKÉMON APPEARED! ✨")
            print("================================")
            print(f"Name:     {pokemon_name} (# {random_id})")
            print(f"Type:     {types_str}")
            print(f"Height:   {height_m} m")
            print(f"Weight:   {weight_kg} kg")
            print(f"Abilities: {abilities_str}")
            print("================================\n")
            
        else:
            print(f"Error: Could not retrieve data (Status Code: {response.status_code})")
            
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    print("Initializing Pokédex...")
    total_pokemon = get_total_pokemon()
    
    while True:
        fetch_random_pokemon(total_pokemon)
        
        # Ask the user if they want to continue
        user_input = input("Press [ENTER] to catch another, or type 'q' to quit: ").strip().lower()
        if user_input == 'q':
            print("Closing Pokédex. Goodbye!")
            break
