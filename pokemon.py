import random
import requests

def get_random_pokemon():
    # As of Generation 9 (The Teal Mask / The Indigo Disk), there are 1025 official Pokemon
    max_pokemon_id = 1025
    
    # Choose a random ID between 1 and 1025
    random_id = random.randint(1, max_pokemon_id)
    
    # The PokéAPI URL for the specific Pokemon
    api_url = f"https://pokeapi.co/api/v2/pokemon/{random_id}"
    
    try:
        print(f"Fetching data for Pokémon #{random_id}...")
        response = requests.get(api_url)
        
        # Check if the request was successful
        if response.status_code == 200:
            data = response.json()
            
            # Extract the name and capitalize the first letter
            pokemon_name = data['name'].capitalize()
            
            # Extract the types (some Pokemon have one type, some have two)
            types = [t['type']['name'].capitalize() for t in data['types']]
            types_str = "/".join(types)
            
            print("\n--- A Wild Pokémon Appeared! ---")
            print(f"Name: {pokemon_name}")
            print(f"Pokédex Number: {random_id}")
            print(f"Type(s): {types_str}")
            print("--------------------------------")
            
        else:
            print(f"Error: Could not retrieve data (Status Code: {response.status_code})")
            
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while connecting to the API: {e}")

if __name__ == "__main__":
    get_random_pokemon()
