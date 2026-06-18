"""
Simple test to interact with the Reachy Mini Gradio app.

Make sure the app is running first:
  python -m reachy_mini_conversation_app.main --gradio

This script will:
1. List available API endpoints
2. Send a test message via the chatbot
"""

from gradio_client import Client
import json

def main():
    try:
        client = Client("http://127.0.0.1:7860/")
        print("✓ Connected to Gradio app")
        
        # Try to see available endpoints
        print("\nAttempting to get API info...")
        try:
            info = client.view_api()
            print("\nAvailable endpoints:")
            for key in info.keys():
                if key.startswith("label"):
                    continue
                print(f"  - {key}")
        except Exception as e:
            print(f"  Could not retrieve full API info: {e}")
        
        # Try the main chat endpoint (usually just / or /chat)
        print("\nTrying to send a message...")
        try:
            # Try calling without specifying api_name (uses default)
            result = client.predict("Hello from Reachy Mini!")
            print(f"✓ Success: {result}")
        except Exception as e:
            print(f"  Error with default endpoint: {e}")
            
            # Try explicit endpoint names
            for endpoint in ["/run", "/chat", "/predict"]:
                try:
                    print(f"\n  Trying endpoint: {endpoint}")
                    result = client.predict("Hello!", api_name=endpoint)
                    print(f"    ✓ Success!")
                    break
                except Exception as e2:
                    print(f"    ✗ Failed: {str(e2)[:100]}")
                    
    except Exception as e:
        print(f"✗ Connection failed: {e}")
        print("\nMake sure the Gradio app is running:")
        print("  python -m reachy_mini_conversation_app.main --gradio")

if __name__ == "__main__":
    main()
