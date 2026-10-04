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
    zoom: float = 0.08,
) -> str:
    """Build an FFmpeg zoompan filter string for the given motion type.

    The zoompan filter works at a default internal fps of 25.  We compute
    the total number of frames ('d') based on duration * fps, then set the
    zoom / pan expressions accordingly.

    `zoom` is the Ken Burns strength — how far the move travels across the
    frame (0.08 = gentle, 0.25 = strong). It comes from the project's
    `motion_zoom` (the dashboard's "Image motion" control) so the strength is
    chosen per project instead of being baked into the engine.

    Returns:
        A complete FFmpeg -vf filter string (may include scale + zoompan + crop).
    """
    if isinstance(motion, str):
        try:
            motion = MotionType(motion.lower())
        except ValueError:
            motion = MotionType.NONE

    total_frames = int(duration * fps)

    # One slider drives every move coherently:
    z     = max(0.0, float(zoom or 0.0))   # travel of a zoom
    panz  = z * 0.6                        # a pan needs headroom either side
    driftz = z * 0.5                       # drift is subtler than a pan
    cut0  = 1.0 + z * 1.8                  # punch-in starts already tight
    cutpush = z * 0.3                      # and keeps pushing a little
    cut1  = cut0 + cutpush                 # where the punch-in lands
    cutback = 1.0 + z * 1.4                # where a pull-back eases out to

    z4      = f"{z:.4f}"
    zmax4   = f"{1.0 + z:.4f}"
    pan4    = f"{1.0 + panz:.4f}"
    drift4  = f"{1.0 + driftz:.4f}"
    cut0s   = f"{cut0:.4f}"
    cut1s   = f"{cut1:.4f}"
    cutpushs = f"{cutpush:.4f}"
    cutbacks = f"{cutback:.4f}"
    drift_amp = f"{min(0.012 * (driftz / 0.02 if driftz else 0.0), 0.035):.4f}"

    # All filters start by upscaling the image so zoompan has room to work,
    # then crop back to the target resolution.
    # We use 2x the target size as the zoompan canvas.
    canvas_w = width * 2
    canvas_h = height * 2

    base_scale = f"scale={canvas_w}:{canvas_h}:force_original_aspect_ratio=increase,crop={canvas_w}:{canvas_h}"

    if motion == MotionType.ZOOM_IN:
        # Zoom in 1.0 → 1+z centered (z = the project's motion strength)
        zoom_expr = f"zoompan=z='min(1.0+{z4}*on/{total_frames},{zmax4})':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.ZOOM_OUT:
        # Zoom out 1+z → 1.0 centered
        zoom_expr = f"zoompan=z='if(eq(on,1),{zmax4},max(1.0,zoom-{z4}/{total_frames}))':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.PAN_LEFT:
        # Pan right-to-left at constant zoom; x sweeps the extra-space width
        zoom_expr = f"zoompan=z='{pan4}':d={total_frames}:x='(iw-iw/zoom)*({total_frames}-on)/{total_frames}':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.PAN_RIGHT:
        # Pan left-to-right at constant zoom
        zoom_expr = f"zoompan=z='{pan4}':d={total_frames}:x='(iw-iw/zoom)*on/{total_frames}':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.ZOOM_IN_LEFT:
        # Zoom in 1.0 → 1+z, anchored to left edge
        zoom_expr = f"zoompan=z='min(1.0+{z4}*on/{total_frames},{zmax4})':d={total_frames}:x='0':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.ZOOM_IN_RIGHT:
        # Zoom in 1.0 → 1+z, anchored to right edge
        zoom_expr = f"zoompan=z='min(1.0+{z4}*on/{total_frames},{zmax4})':d={total_frames}:x='iw-iw/zoom':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.ZOOM_OUT_LEFT:
        # Zoom out 1+z → 1.0, anchored to left edge
        zoom_expr = f"zoompan=z='if(eq(on,1),{zmax4},max(1.0,zoom-{z4}/{total_frames}))':d={total_frames}:x='0':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.ZOOM_OUT_RIGHT:
        # Zoom out 1+z → 1.0, anchored to right edge
        zoom_expr = f"zoompan=z='if(eq(on,1),{zmax4},max(1.0,zoom-{z4}/{total_frames}))':d={total_frames}:x='iw-iw/zoom':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.TILT_UP:
        # Pan bottom-to-top at constant zoom
        zoom_expr = f"zoompan=z='{pan4}':d={total_frames}:x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*on/{total_frames}':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.TILT_DOWN:
        # Pan top-to-bottom at constant zoom
        zoom_expr = f"zoompan=z='{pan4}':d={total_frames}:x='iw/2-(iw/zoom/2)':y='(ih-ih/zoom)*({total_frames}-on)/{total_frames}':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.CUT_IN:
        # Punch-in: opens already tight and keeps pushing in.
        zoom_expr = f"zoompan=z='min({cut0s}+{cutpushs}*on/{total_frames},{cut1s})':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.CUT_OUT:
        # Pull-back: opens tight and eases out.
        zoom_expr = f"zoompan=z='if(eq(on,1),{cut0s},max({cutbacks},zoom-{cutpushs}/{total_frames}))':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={width}x{height}:fps={fps}"
        return f"{base_scale},{zoom_expr}"

    elif motion == MotionType.CAMERA_DRIFT:
        # Gentle drift with a slow push — always the subtlest move
        zoom_expr = (
            f"zoompan=z='min(1.0+{z4}*0.5*on/{total_frames},{drift4})'"
            f":d={total_frames}"
            f":x='iw/2-(iw/zoom/2)+iw/zoom*{drift_amp}*sin(2*PI*on/{total_frames})'"
            f":y='ih/2-(ih/zoom/2)+ih/zoom*{drift_amp}*0.7*cos(2*PI*on/{total_frames})'"
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
