from gradio_client import Client
import json

try:
    client = Client("http://127.0.0.1:7860/")
    
    # Get the API info
    info = client.view_api()
    
    print("Available endpoints:")
    print(json.dumps(info, indent=2))
    
except Exception as e:
    print(f"Error: {e}")
    print("\nTrying alternative approach...")
    
    try:
        client = Client("http://127.0.0.1:7860/")
        print("Client connected successfully")
        print(f"Space info: {client.info}")
    except Exception as e2:
        print(f"Alternative also failed: {e2}")
