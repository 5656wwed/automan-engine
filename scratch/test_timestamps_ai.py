import asyncio
import os
from unittest.mock import patch
from app.core.timestamps import build_timestamps_content

class MockScene:
    def __init__(self, script, title=None):
        self.script = script
        self.title = title

class MockResponse:
    def __init__(self, status, json_data):
        self.status = status
        self._json_data = json_data
        
    async def json(self):
        return self._json_data
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

class MockClientSession:
    def __init__(self, status=200, json_data=None):
        self.status = status
        self.json_data = json_data or {
            "choices": [
                {
                    "message": {
                        "content": "The Kokoda Battle Begins"
                    }
                }
            ]
        }
        self.post_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return MockResponse(self.status, self.json_data)
        
    async def __aenter__(self):
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

async def test_groq_success():
    scenes = [
        MockScene("In August of 1942, a small group of Australian soldiers arrived at Kokoda."),
        MockScene("The weather was harsh, and they had to struggle through muddy terrain."),
        MockScene("The initial defence of Kokoda village was a critical moment in the campaign."),
        MockScene("By this point, reinforcements from the 2/14th Battalion arrived to secure the path."),
    ]
    durations = [120.0, 100.0, 90.0, 110.0]

    mock_session = MockClientSession()

    os.environ["GROQ_API_KEY"] = "mock_key"

    # Patch aiohttp.ClientSession
    with patch("aiohttp.ClientSession", return_value=mock_session):
        res = await build_timestamps_content(scenes, durations, transition_duration=0.5, target_interval=180.0)
        
        # Verify result
        print("Result with Groq success:")
        print(res)
        
        assert "The Kokoda Battle Begins" in res
        
        # Verify that mock_session.post was called with expected headers and payload
        calls = mock_session.post_calls
        assert len(calls) == 2, f"Expected 2 calls to post, got {len(calls)}"
        
        # Verify call arguments
        url, kwargs = calls[0]
        assert url == "https://api.groq.com/openai/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer mock_key"
        payload = kwargs["json"]
        assert payload["model"] == "llama3-8b-8192"
        assert "In August of 1942" in payload["messages"][0]["content"]

        print("SUCCESS test passed.")

async def test_groq_failure():
    scenes = [
        MockScene("In August of 1942, a small group of Australian soldiers arrived at Kokoda."),
        MockScene("The weather was harsh, and they had to struggle through muddy terrain."),
        MockScene("The initial defence of Kokoda village was a critical moment in the campaign."),
        MockScene("By this point, reinforcements from the 2/14th Battalion arrived to secure the path."),
    ]
    durations = [120.0, 100.0, 90.0, 110.0]

    mock_session = MockClientSession(status=500)

    os.environ["GROQ_API_KEY"] = "mock_key"

    with patch("aiohttp.ClientSession", return_value=mock_session):
        res = await build_timestamps_content(scenes, durations, transition_duration=0.5, target_interval=180.0)
        
        # Verify result falls back to heuristic
        print("Result with Groq failure (should fallback to heuristic):")
        print(res)
        
        assert "In August of 1942" in res
        assert "The initial defence of Kokoda" in res
        print("FAILURE test passed.")

if __name__ == "__main__":
    asyncio.run(test_groq_success())
    asyncio.run(test_groq_failure())
