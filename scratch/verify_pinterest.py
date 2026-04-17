import asyncio
import sys
import os
sys.path.append(os.getcwd())
import downloader as dl

async def verify_fallback():
    # This should trigger the fallback since we know yt-dlp fails on this
    url = "https://pin.it/4OWAkrWb8"
    print(f"Testing fallback for: {url}")
    try:
        info = await dl.fetch_info(url)
        print("✅ Fallback Success!")
        print(f"Title: {info['title']}")
        print(f"Thumbnail: {info['thumbnail']}")
        print(f"Media Types: {info['media_types']}")
        
        # Check if thumbnail is actually an image URL
        if info['thumbnail'] and info['thumbnail'].startswith('http'):
            print("✅ Valid image URL found.")
        else:
            print("❌ No valid image URL found.")
            
    except Exception as e:
        print(f"❌ Fallback Failed: {e}")

if __name__ == "__main__":
    asyncio.run(verify_fallback())
