"""The Audio spy of F10 ``06`` §0.4: a fake ``AudioService`` that records ``take_music``, the
handle's ``play``/``stop``/``release``, ``stop_story_audio``, and ``play_ui`` calls, in order,
as tuples in ``calls``. F08's real service replaces it once built (F08 step 7)."""


class MusicHandleSpy:
    def __init__(self, spy: "AudioSpy", owner: str) -> None:
        self.spy = spy
        self.owner = owner

    def play(self, file: str, *, loop: bool, fadein: float) -> None:
        self.spy.calls.append(("play", file, loop, fadein))

    def stop(self, *, fadeout: float) -> None:
        self.spy.calls.append(("stop", fadeout))

    def release(self) -> None:
        self.spy.calls.append(("release",))


class AudioSpy:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def take_music(self, owner: str) -> MusicHandleSpy:
        self.calls.append(("take_music", owner))
        return MusicHandleSpy(self, owner)

    def stop_story_audio(self, seconds: float) -> None:
        self.calls.append(("stop_story_audio", seconds))

    def play_ui(self, file: str) -> None:
        self.calls.append(("play_ui", file))

    def names(self) -> list[str]:
        return [call[0] for call in self.calls]

    # F08 step 4: the App's slots and ``install_audio`` reach whatever is ``App.audio``;
    # these record nothing, so the calls above stay F10's.

    def register(self, router) -> None:
        from engine.app.story import AUDIO_COMMANDS

        for command_type in AUDIO_COMMANDS:
            router.register(command_type, lambda cmd: None)

    def handle_event(self, raw) -> bool:
        return False

    def update(self, now: float) -> None:
        pass

    def shutdown(self) -> None:
        pass
