import asyncio
from app.core.timestamps import build_timestamps_content

class MockScene:
    def __init__(self, script, title=None):
        self.script = script
        self.title = title

async def test():
    scenes = [
        MockScene("In August of 1942, a small group of Australian soldiers arrived at Kokoda."),
        MockScene("The weather was harsh, and they had to struggle through muddy terrain."),
        MockScene("The initial defence of Kokoda village was a critical moment in the campaign."),
        MockScene("By this point, reinforcements from the 2/14th Battalion arrived to secure the path."),
    ]
    durations = [120.0, 100.0, 90.0, 110.0]
    
    res = await build_timestamps_content(scenes, durations, transition_duration=0.5, target_interval=180.0)
    print("Result without API key:")
    print(res)

if __name__ == "__main__":
    asyncio.run(test())
