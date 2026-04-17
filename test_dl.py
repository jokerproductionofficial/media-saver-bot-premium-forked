import asyncio
import downloader as dl
import sys
import logging

sys.stdout.reconfigure(encoding='utf-8')
logging.basicConfig(level=logging.INFO)

async def run_test():
    test_urls = [
        ("youtube", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
        ("instagram", "https://www.instagram.com/p/C_mP1Mqvz4u/"),
        ("tiktok", "https://www.tiktok.com/@tiktok/video/7106097148560018730"),
        ("pinterest", "https://pin.it/4OWAkrWb8")
    ]

    for plat, url in test_urls:
        print(f"\n--- Testing {plat.upper()} ---")
        try:
            print(f"Fetching info for {url} ...")
            info = await dl.fetch_info(url)
            print(f"✅ Success! Title: {info['title'][:50]}")
            print(f"Qualities: {info.get('available_qualities', [])}")
            
            # optionally test the download on youtube
            if plat == "youtube":
                print(f"Downloading {plat} video ...")
                path = await dl.download_media(url, plat, 99999, "best")
                print(f"✅ DL Success! Saved at: {path}")
                dl.cleanup_file(path)
        except Exception as e:
            print(f"❌ ERROR on {plat}: {e}")

if __name__ == "__main__":
    asyncio.run(run_test())
