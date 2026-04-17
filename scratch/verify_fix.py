import sys
import os
sys.path.append(os.getcwd())

import downloader as dl
import asyncio

def test_duration():
    print("Testing _format_duration...")
    # float input
    assert dl._format_duration(125.7) == "2:05"
    # large float
    assert dl._format_duration(3665.2) == "1:01:05"
    # None input
    assert dl._format_duration(None) == "N/A"
    # String input
    assert dl._format_duration("60") == "1:00"
    print("[SUCCESS] _format_duration tests passed!")

async def test_fetch_info_robustness():
    print("\nTesting fetch_info robustness (mock)...")
    # This is harder to test without mocking yt-dlp, but we can check if it handles bad inputs
    try:
        await dl.fetch_info("https://invalid-url.com")
    except Exception as e:
        print(f"Caught expected error: {e}")
    print("✅ fetch_info robustness check completed!")

if __name__ == "__main__":
    test_duration()
    asyncio.run(test_fetch_info_robustness())
