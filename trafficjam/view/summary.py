"""Win summary panel with score and star rating."""
from __future__ import annotations

import pygame

from .hud import Button

PANEL = (32, 34, 44)
TEXT = (240, 242, 248)
SUBTLE = (170, 174, 186)
STAR_ON = (255, 205, 70)
STAR_OFF = (80, 82, 92)


def score_for(player_moves: int, par: int) -> tuple[int, int]:
    """Return (score 0-1000, stars 1-3)."""
    player_moves = max(player_moves, 1)
    score = max(0, round(1000 * par / player_moves))
    if player_moves <= par:
        stars = 3
    elif player_moves <= round(par * 1.25):
        stars = 2
    else:
        stars = 1
    return score, stars


def _star(surface, cx, cy, r, on):
    import math
    pts = []
    for i in range(10):
        ang = -math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.45
        pts.append((cx + math.cos(ang) * rad, cy + math.sin(ang) * rad))
    pygame.draw.polygon(surface, STAR_ON if on else STAR_OFF, pts)


class Summary:
    def __init__(self, screen_w, screen_h, fonts):
        self.w, self.h = screen_w, screen_h
        self.f_big = fonts["title"]
        self.f_body = fonts["body"]
        self.f_small = fonts["small"]
        cx = screen_w / 2
        self.next_btn = Button((cx - 200, screen_h / 2 + 110, 180, 46), "Next Level")
        self.replay_btn = Button((cx + 20, screen_h / 2 + 110, 180, 46), "Replay")

    def draw(self, surface, *, player_moves, par, mouse, has_next=True):
        score, stars = score_for(player_moves, par)
        overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        surface.blit(overlay, (0, 0))

        pw, ph = 460, 320
        px, py = (self.w - pw) / 2, (self.h - ph) / 2
        pygame.draw.rect(surface, PANEL, (px, py, pw, ph), border_radius=16)

        title = self.f_big.render("SOLVED!", True, (120, 230, 150))
        surface.blit(title, title.get_rect(center=(self.w / 2, py + 44)))

        for i in range(3):
            _star(surface, self.w / 2 - 60 + i * 60, py + 110, 26, i < stars)

        lines = [
            f"Your moves: {player_moves}",
            f"Best possible: {par}",
            f"Score: {score}",
        ]
        for i, line in enumerate(lines):
            t = self.f_body.render(line, True, TEXT)
            surface.blit(t, t.get_rect(center=(self.w / 2, py + 160 + i * 30)))

        self.next_btn.enabled = has_next
        self.next_btn.draw(surface, self.f_body, mouse)
        self.replay_btn.draw(surface, self.f_body, mouse)
        return score, stars
