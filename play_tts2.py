from reachy_mini import ReachyMini
from openai import OpenAI
import tempfile
import os
from dotenv import load_dotenv

load_dotenv()

robot = ReachyMini()

# Option 1: Use OpenAI TTS (if you have API key)
def speak_openai(text: str, voice: str = "alloy"):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        response = client.audio.speech.create(model="tts-1", voice=voice, input=text)
        response.stream_to_file(tmp.name)
        robot.media.play(tmp.name)
        os.unlink(tmp.name)

# Option 2: Use free Hugging Face TTS (no key needed)
def speak_hf(text: str):
    from gradio_client import Client
    client = Client("facebook/mms-tts")
    result = client.predict(text_input=text, language_dropdown="eng", api_name="/predict")
    robot.media.play(result)

# Script example
speak_openai("Hello! I am Reachy Mini!")
robot.head.look_at(x=0, y=0.5, z=0)  # Look up while speaking