import aiohttp
import asyncio
import re

async def research_pinterest(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(url, allow_redirects=True) as resp:
            print(f"Status: {resp.status}")
            print(f"Final URL: {resp.url}")
            html = await resp.text()
            
            # Simple meta tag extraction
            og_image = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html)
            if og_image:
                print(f"OG Image: {og_image.group(1)}")
            else:
                print("OG Image not found in meta tags.")
            
            # Title
            og_title = re.search(r'<meta[^>]+property="og:title"[^>]+content="([^"]+)"', html)
            if og_title:
                print(f"OG Title: {og_title.group(1)}")

if __name__ == "__main__":
    asyncio.run(research_pinterest("https://pin.it/4OWAkrWb8"))
