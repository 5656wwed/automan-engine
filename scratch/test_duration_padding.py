import asyncio
import unittest
import tempfile
import shutil
from unittest.mock import MagicMock, patch, AsyncMock
from pathlib import Path
from app.core.project import SceneConfig, Project, ProjectConfig
from app.renderer.scene_renderer import SceneRenderer

class MockTTSResult:
    def __init__(self, duration, word_timestamps=None):
        self.duration = duration
        self.word_timestamps = word_timestamps or {
            "wordAlignment": {
                "words": ["hello", "world"],
                "wordStartTimeSeconds": [0.5, 1.2]
            }
        }

class TestSceneRendererDuration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Create temp dir for project paths
        self.temp_dir = Path(tempfile.mkdtemp())
        self.project_dir = self.temp_dir / "project"
        self.project_dir.mkdir()
        self.output_dir = self.temp_dir / "output"
        self.output_dir.mkdir()

        # Create a mock project
        self.project = MagicMock(spec=Project)
        self.project.project_dir = self.project_dir
        self.project.project_output_dir = self.output_dir
        self.project.scene_count = 1
        
        self.project.config = MagicMock(spec=ProjectConfig)
        self.project.config.duration_padding = 0.5
        self.project.config.transition_duration = 0.5
        self.project.config.transition = "fade"
        self.project.config.resolution = "1920x1080"
        self.project.config.fps = 30
        self.project.config.quality = "high"
        self.project.config.voice = None
        self.project.config.motion = "none"
        self.project.config.randomize_motion = False

        # Mock VoiceManager
        self.voice_manager = MagicMock()
        
        # Instantiate renderer
        self.renderer = SceneRenderer(self.project, self.voice_manager)

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @patch("app.renderer.scene_renderer.get_audio_duration")
    @patch("app.renderer.scene_renderer.add_silence_padding")
    @patch("app.renderer.scene_renderer.image_to_video")
    @patch("app.renderer.scene_renderer.add_audio_to_video")
    @patch("app.renderer.scene_renderer._find_font")
    @patch("app.renderer.scene_renderer._find_sfx")
    async def test_duration_without_overlay(
        self, mock_find_sfx, mock_find_font, mock_add_audio, mock_img_to_vid, mock_pad_audio, mock_audio_dur
    ):
        # Voice duration is 3.0s, padding is 0.5s, transition is 0.5s.
        # Target duration: 3.0 + 0.5 + 0.5 = 4.0s
        mock_audio_dur.side_effect = lambda path: 4.0 if "padded" in str(path) else 3.0
        mock_find_font.return_value = Path("mock_font.ttf")
        mock_find_sfx.return_value = Path("mock_sfx.mp3")

        self.voice_manager.generate = AsyncMock(return_value=MockTTSResult(3.0))

        scene = SceneConfig(
            image="mock_image.png",
            script="Hello world",
            overlay_text=None,
            duration_padding=0.5
        )

        final_clip, duration = await self.renderer.render_scene(scene, 0)
        
        # Target duration should be 4.0s
        self.assertEqual(duration, 4.0)
        
        # Verify that add_silence_padding was called with needed_padding = 1.0s (4.0s - 3.0s voice)
        mock_pad_audio.assert_called_once()
        args, kwargs = mock_pad_audio.call_args
        self.assertAlmostEqual(kwargs["padding_seconds"], 1.0)

    @patch("app.renderer.scene_renderer.get_audio_duration")
    @patch("app.renderer.scene_renderer.add_silence_padding")
    @patch("app.renderer.scene_renderer.image_to_video")
    @patch("app.renderer.scene_renderer.add_audio_to_video")
    @patch("app.renderer.scene_renderer._find_font")
    @patch("app.renderer.scene_renderer._find_sfx")
    async def test_duration_extended_for_overlay(
        self, mock_find_sfx, mock_find_font, mock_add_audio, mock_img_to_vid, mock_pad_audio, mock_audio_dur
    ):
        # Voice duration: 3.0s, padding: 0.5s, transition: 0.5s. Base duration: 4.0s.
        # Overlay starts at 2.5s (late in the 3.0s voice clip).
        # overlay_type_duration (typing speed duration) is 2.0s. Vanish delay is 1.0s.
        # Required for overlay: 2.5 (start) + 2.0 (typing) + 1.0 (vanish) + 0.5 (transition) = 6.0s.
        # Since base duration (4.0s) < 6.0s, the scene duration should be extended to 6.0s.
        mock_audio_dur.side_effect = lambda path: 6.0 if "padded" in str(path) else 3.0
        mock_find_font.return_value = Path("mock_font.ttf")
        mock_find_sfx.return_value = Path("mock_sfx.mp3")

        # Mock word alignment: "world" is spoken at 2.5s
        timestamps = {
            "wordAlignment": {
                "words": ["hello", "world"],
                "wordStartTimeSeconds": [0.5, 2.5]
            }
        }
        self.voice_manager.generate = AsyncMock(return_value=MockTTSResult(3.0, timestamps))

        scene = SceneConfig(
            image="mock_image.png",
            script="Hello world",
            overlay_text="world",
            duration_padding=0.5
        )

        final_clip, duration = await self.renderer.render_scene(scene, 0)
        
        # Target duration should be extended to 6.0s
        self.assertEqual(duration, 6.0)
        
        # Verify that add_silence_padding was called with needed_padding = 3.0s (6.0s - 3.0s voice)
        mock_pad_audio.assert_called_once()
        args, kwargs = mock_pad_audio.call_args
        self.assertAlmostEqual(kwargs["padding_seconds"], 3.0)

if __name__ == "__main__":
    unittest.main()
