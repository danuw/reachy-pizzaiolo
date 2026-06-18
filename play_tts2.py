from reachy_mini import ReachyMini
from openai import OpenAI
import tempfile
import os
import time
import sys
from dotenv import load_dotenv

load_dotenv()

robot = ReachyMini()

def speak_openai(text: str, voice: str = "alloy"):
    """Generate and play TTS audio with optional robot movements."""
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    # Generate TTS audio
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        response = client.audio.speech.create(
            model="tts-1",
            voice=voice,
            input=text
        )
        response.stream_to_file(tmp.name)
        temp_file = tmp.name
    
    try:
        print(f"Speaking: {text}")
        
        # Try using winsound on Windows
        if sys.platform == "win32":
            try:
                import winsound
                winsound.PlaySound(temp_file, winsound.SND_FILENAME)
                return
            except Exception as e:
                print(f"Winsound failed: {e}, trying alternative method...")
        
        # Fallback: try using pydub and simpleaudio
        try:
            from pydub import AudioSegment
            from pydub.playback import play
            sound = AudioSegment.from_mp3(temp_file)
            play(sound)
            return
        except Exception as e:
            print(f"Pydub failed: {e}, trying sounddevice...")
        
        # Last resort: use sounddevice
        try:
            import sounddevice as sd
            import soundfile as sf
            data, samplerate = sf.read(temp_file)
            sd.play(data, samplerate)
            sd.wait()
        except Exception as e:
            print(f"All audio playback methods failed: {e}")
            print(f"Audio file saved at: {temp_file}")
            
    finally:
        # Clean up temp file (but don't delete if we need to keep it for fallback)
        try:
            time.sleep(0.5)  # Give time for playback to finish
            os.unlink(temp_file)
        except:
            pass

# Example script
print("Initializing Reachy Mini...")
robot.head.look_at(x=0, y=0.5, z=0)  # Look up
time.sleep(0.5)

speak_openai("Hello! I am Reachy Mini!")

# Optional: Add some more interactions
time.sleep(1)
robot.head.look_at(x=0.5, y=0.3, z=0)  # Look right
speak_openai("I can follow scripts and have conversations!")

print("Done!")