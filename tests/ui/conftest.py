"""Shared setup for screen tests: pygame initialized, event queue empty."""

import pygame
import pytest


@pytest.fixture(autouse=True)
def pygame_ready():
    pygame.init()
    pygame.event.clear()
    yield
    pygame.quit()
