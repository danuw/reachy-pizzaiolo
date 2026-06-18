from gradio_client import Client
import os
from dotenv import load_dotenv

load_dotenv()

# Connect to the local Gradio app
client = Client("http://127.0.0.1:7860/")

# Try a simple text-based interaction without video
try:
    result = client.predict(
        # Try with minimal required parameters
        param_6="Hello from Reachy Mini!",  # prompt/message
        api_name="/set_input_gradio"
    )
    print("Success!")
    print(result)
except Exception as e:
    print(f"Error with minimal params: {e}")
    
# Alternative: try to find what methods are available
print("\n--- Available methods ---")
try:
    for attr in dir(client):
        if not attr.startswith('_'):
            print(f"  {attr}")
except:
    pass
