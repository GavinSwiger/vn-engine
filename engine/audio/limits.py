"""The presentation's audio limits and mixer constants (F08 ``04-technical.md`` §7.2, §11, §12).

The story-state limits (``MUSIC_SEQUENCE_MAX``, ``SOUND_LOOPS_MAX``, ``ONESHOTS_PER_BURST``,
``AUDIO_BURST_MAX``) live in ``runtime/limits.py``; these are the ones only the presentation
uses. The mixer rate and buffer are constants, not config keys (§13).
"""

from typing import Final

from engine.core.constants import MB

# Files (§7.4, security checklist 3).
MUSIC_MAX_BYTES: Final = 64 * MB          # 67,108,864: music is streamed, never decoded whole
SOUND_MAX_BYTES: Final = 8 * MB           # 8,388,608: effects and voice
SOUND_MAX_SECONDS: Final = 600            # declared length of an effect or voice

# Mixer (§7.2; 04 §2 Q2(d)).
MIXER_RATE: Final = 48_000                # Hz
MIXER_SIZE: Final = -16                   # signed 16-bit samples
MIXER_BUFFER: Final = 512                 # frames (10.7 ms at 48 kHz)
MIXER_CHANNELS: Final = 21                # every channel is reserved: none is picked by SDL
VOICE_CHANNEL: Final = 0
POOL_CHANNELS: Final = range(1, 5)        # 1 blips (F06), 2–4 UI sounds (F10, F07, F11)
BLIP_CHANNEL: Final = 1                   # F06's play_blip (F06 SPEC §5; F23 07 I-4)
UI_CHANNELS: Final = range(2, 5)          # play_ui: F10, F07, F11, F23's plugin one-shots
EFFECT_CHANNELS: Final = range(5, 21)     # 16 story effects
DECODED_BYTES_PER_SECOND: Final = 192_000  # 48 kHz × 2 channels × 2 bytes: a Sound's cache cost

# Timing (§7.1, §7.6, §7.9).
SWITCH_LEAD_S: Final = 0.15
SAME_BURST_S: Final = 0.1
REOPEN_DEBOUNCE_S: Final = 0.5
SKIP_FADE_CAP_S: Final = 0.2
BLIP_STALE_S: Final = 0.05                # a blip decoded later than this after its ask is dropped

# Logging (§7.4 "Logging cap", as F01's ``ASSET_PROBLEM_LOG_LIMIT``).
AUDIO_LOG_PATHS_MAX: Final = 1_000
# Files that failed to read or decode are not read again (bounded, oldest forgotten first).
FAILED_FILES_MAX: Final = 256
