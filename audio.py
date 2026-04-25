import asyncio
import edge_tts

# STM32 projen için 10 adet anons
anonslar = {
    "0001": "Kapı açılıyor.",
    "0002": "Kapı kapandı.",
    "0003": "Lütfen kartınızı okutunuz.",
    "0004": "Geçersiz kart, giriş reddedildi.",
    "0005": "Sistem aktif hale getirildi.",
    "0006": "Giriş başarılı, hoş geldiniz.",
    "0007": "Lütfen bekleyiniz, işlem yapılıyor.",
    "0008": "Hatalı şifre girdiniz.",
    "0009": "Dikkat! Güvenlik alarmı devreye girdi.",
    "0010": "Sistem kapatılıyor, iyi günler."
}

async def generate_anonslar():
    for num, text in anonslar.items():
        # Kadın sesi için Emel, erkek sesi için Ahmet seçebilirsin
        voice = "tr-TR-EmelNeural" 
        
        communicate = edge_tts.Communicate(text, voice, rate="+10%")
        await communicate.save(f"{num}.mp3")
        print(f"Oluşturuldu: {num}.mp3 -> {text}")

if __name__ == "__main__":
    asyncio.run(generate_anonslar())
