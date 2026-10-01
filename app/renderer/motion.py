"""Ken Burns motion effects via FFmpeg zoompan filter."""

from __future__ import annotations

import random
from enum import Enum
from typing import Optional

from app.core.config import MotionType
from app.utils.logger import get_logger

log = get_logger("renderer.motion")


def get_motion_filter(
    motion: MotionType | str,
    width: int = 1920,
    height: int = 1080,
    duration: float = 5.0,
    fps: int = 30,
) -> str:
    """Build an FFmpeg zoompan filter string for the given motion type.

    The zoompan filter works at a default internal fps of 25.  We compute
    the total number of frames ('d') based on duration * fps, then set the
    zoom / pan expressions accordingly.

    Returns:
        A complete FFmpeg -vf filter string (may include scale + zoompan + crop).
    """
    if isinstance(motion, str):
        try:
            motion = MotionType(motion.lower())
        except ValueError:
            motion = MotionType.NONE

    total_frames = int(duration * fps)

    # All filters start by upscaling the image so zoompan has room to work,
    # then crop back to the target resolution.
    # We use 2x the target size as the zoompan canvas.
    canvas_w = width * 2
    canvas_h = height * 2

    base_scale = f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,crop={canvas_w}:{canvas_h}"

    if motion == MotionType.ZOOM_IN:
        # Zoom from 1.0 → 1.08 centered (8% zoom, fills full duration)
        zoom_expr = f"zoompan=z='min(1.0+0.08*on/{total_frames},1.08)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.ZOOM_OUT:
        # Zoom from 1.08 → 1.0 centered
        zoom_expr = f"zoompan=z='if(eq(on,1),1.08,max(1.0,zoom-0.08/{total_frames}))':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.PAN_LEFT:
        # Pan right-to-left at constant zoom 1.05; x sweeps full extra-space width
        zoom_expr = f"zoompan=z='1.05':d={total_frames}:x='(iw-iw/zoom)*({total_frames}-on)/{total_frames}':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.PAN_RIGHT:
        # Pan left-to-right at constant zoom 1.05
        zoom_expr = f"zoompan=z='1.05':d={total_frames}:x='(iw-iw/zoom)*on/{total_frames}':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.ZOOM_IN_LEFT:
        # Zoom in 1.0 → 1.08, anchored to left edge
        zoom_expr = f"zoompan=z='min(1.0+0.08*on/{total_frames},1.08)':d={total_frames}:x='0':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.ZOOM_IN_RIGHT:
        # Zoom in 1.0 → 1.08, anchored to right edge
        zoom_expr = f"zoompan=z='min(1.0+0.08*on/{total_frames},1.08)':d={total_frames}:x='iw-iw/zoom':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.ZOOM_OUT_LEFT:
        # Zoom out 1.08 → 1.0, anchored to left edge
        zoom_expr = f"zoompan=z='if(eq(on,1),1.08,max(1.0,zoom-0.08/{total_frames}))':d={total_frames}:x='0':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.ZOOM_OUT_RIGHT:
        # Zoom out 1.08 → 1.0, anchored to right edge
        zoom_expr = f"zoompan=z='if(eq(on,1),1.08,max(1.0,zoom-0.08/{total_frames}))':d={total_frames}:x='iw-iw/zoom':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.TILT_UP:
        # Pan bottom-to-top at constant zoom 1.05
        zoom_expr = f"zoompan=z='1.05':d={total_frames}:x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{total_frames}':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.TILT_DOWN:
        # Pan top-to-bottom at constant zoom 1.05
        zoom_expr = f"zoompan=z='1.05':d={total_frames}:x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*({total_frames}-on)/{total_frames}':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.CUT_IN:
        # Punch-in: starts already tight (1.30) and keeps pushing to 1.36.
        zoom_expr = f"zoompan=z='min(1.30+0.06*on/{total_frames},1.36)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.CUT_OUT:
        # Pull-back: starts tight (1.30) and eases out towards 1.22.
        zoom_expr = f"zoompan=z='if(eq(on,1),1.30,max(1.22,zoom-0.06/{total_frames}))':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.CAMERA_DRIFT:
        # Very subtle drift with gentle zoom 1.0 → 1.04
        zoom_expr = (
            f"zoompan=z='min(1.0+0.04*on/{total_frames},1.04)'"
            f":d={total_frames}"
            f":x='iw/2-(iw/zoom/2)+iw/zoom*0.01*sin(2*PI*on/{total_frames})'"
            f":y='ih/2-(ih/zoom/2)+ih/zoom*0.008*cos(2*PI*on/{total_frames})'"
            f":s={width}x{height}:fps={fps}"
        )
        return f"{base_scale},{zoom_expr}"

    else:
        # NONE — static, just scale and pad
        return f"scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black"


# ---------------------------------------------------------------------------
# Motion randomizer
# ---------------------------------------------------------------------------
_CINEMATIC_MOTIONS = [
    MotionType.ZOOM_OUT,
    MotionType.ZOOM_IN,
    MotionType.PAN_LEFT,
    MotionType.PAN_RIGHT,
    MotionType.ZOOM_IN_LEFT,
    MotionType.ZOOM_IN_RIGHT,
    MotionType.ZOOM_OUT_LEFT,
    MotionType.ZOOM_OUT_RIGHT,
    MotionType.CAMERA_DRIFT,
]

_MOTION_WEIGHTS = [
    25,  # zoom_out
    20,  # zoom_in
    15,  # pan_left
    15,  # pan_right
    10,  # zoom_in_left
    10,  # zoom_in_right
    10,  # zoom_out_left
    10,  # zoom_out_right
    5,   # camera_drift
]


def pick_random_motion(seed: Optional[int] = None) -> MotionType:
    """Select a weighted-random motion type. Favours zoom_out."""
    rng = random.Random(seed)
    return rng.choices(_CINEMATIC_MOTIONS, weights=_MOTION_WEIGHTS, k=1)[0]


def resolve_scene_motion(
    scene_motion: Optional[str],
    project_motion: Optional[str],
    randomize: bool = True,
    scene_index: int = 0,
) -> MotionType:
    """Determine the motion for a scene following the override chain:
    scene-level > project-level > randomized/default.
    """
    # 1. Scene-level explicit override
    if scene_motion:
        try:
            return MotionType(scene_motion.lower())
        except ValueError:
            log.warning(f"Scene {scene_index}: unknown motion '{scene_motion}', falling back.")

    # 2. Project-level default
    if project_motion:
        try:
            return MotionType(project_motion.lower())
        except ValueError:
            pass

    # 3. Randomize or default
    if randomize:
        return pick_random_motion(seed=scene_index)

    return MotionType.ZOOM_OUT  # hardcoded default
