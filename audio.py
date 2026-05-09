import asyncio
import edge_tts
import os

anonslar = {
    "001": "Hoşgeldiniz.",
    "002": "Kapı açılıyor.",
    "003": "Kapı kilitleniyor.",
    "004": "Kapı kapanıyor. Kapıyı kilitlemek için lütfen sensöre dokununuz",
    "005": "Dolu.",
}

voices = {
    "001": "Welcome.",
    "002": "Door opening.",
    "003": "Door locking",
    "004": "Door closing. Touch the sensor to lock the door.",
    "005": "Full.",
}

async def generate_tr_anonslar():
    for num, text in anonslar.items():
        voice = "tr-TR-EmelNeural"
        
        if not os.path.exists("01"):
            os.makedirs("01")
        communicate = edge_tts.Communicate(text, voice, rate="+2%")
        await communicate.save(f"01/{num}.mp3")
        print(f"Generated: {num}.mp3 -> {text}")

async def generate_en_voices():
    for num, text in voices.items():
        voice = "en-US-AriaNeural"
        
        if not os.path.exists("02"):
            os.makedirs("02")
        communicate = edge_tts.Communicate(text, voice, rate="+2%")
        await communicate.save(f"02/{num}.mp3")
        print(f"Generated: {num}.mp3 -> {text}")


if __name__ == "__main__":
    asyncio.run(generate_tr_anonslar())
    asyncio.run(generate_en_voices())
