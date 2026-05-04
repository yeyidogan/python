import asyncio
import edge_tts

# STM32 projen için 10 adet anons
anonslar = {
    "001": "Hoşgeldiniz.",
    "002": "Kapı açılıyor.",
    "003": "Kapı kilitleniyor.",
    "004": "Kapı kapanıyor.",
    "005": "Dolu.",
}

async def generate_anonslar():
    for num, text in anonslar.items():
        # Kadın sesi için Emel, erkek sesi için Ahmet seçebilirsin
        voice = "tr-TR-EmelNeural" 
        
        communicate = edge_tts.Communicate(text, voice, rate="+2%")
        await communicate.save(f"{num}.mp3")
        print(f"Oluşturuldu: {num}.mp3 -> {text}")

if __name__ == "__main__":
    asyncio.run(generate_anonslar())
