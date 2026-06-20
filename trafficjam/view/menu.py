"""Level-select menu."""
from __future__ import annotations

import pygame

BG = (24, 26, 34)
CARD = (40, 44, 58)
CARD_HOVER = (58, 64, 84)
TEXT = (236, 238, 244)
SUBTLE = (160, 164, 176)
ACCENT = (90, 170, 255)

LEVEL_COLORS = {
    "Beginner": (110, 200, 130),
    "Intermediate": (240, 200, 80),
    "Advanced": (240, 140, 80),
    "Expert": (230, 90, 90),
}


class Menu:
    def __init__(self, screen_w, screen_h, fonts, puzzles):
        self.w, self.h = screen_w, screen_h
        self.f_title = fonts["title"]
        self.f_body = fonts["body"]
        self.f_small = fonts["small"]
        self.puzzles = puzzles  # list of dicts with id, level, min_moves
        self.cards: list[tuple[pygame.Rect, int]] = []
        self._layout()

    def _layout(self):
        self.cards.clear()
        cols = 4
        cw, ch = 150, 110
        gap = 24
        total = cols * cw + (cols - 1) * gap
        x0 = (self.w - total) / 2
        y0 = 150
        for i, p in enumerate(self.puzzles):
            r, c = divmod(i, cols)
            rect = pygame.Rect(x0 + c * (cw + gap), y0 + r * (ch + gap), cw, ch)
            self.cards.append((rect, i))

    def draw(self, surface, mouse, best_scores):
        surface.fill(BG)
        title = self.f_title.render("TRAFFIC JAM", True, TEXT)
        surface.blit(title, title.get_rect(center=(self.w / 2, 60)))
        sub = self.f_body.render("Select a level", True, SUBTLE)
        surface.blit(sub, sub.get_rect(center=(self.w / 2, 100)))

        for rect, idx in self.cards:
            p = self.puzzles[idx]
            hover = rect.collidepoint(mouse)
            pygame.draw.rect(surface, CARD_HOVER if hover else CARD, rect,
                             border_radius=12)
            stripe = LEVEL_COLORS.get(p["level"], ACCENT)
            pygame.draw.rect(surface, stripe, (rect.x, rect.y, rect.w, 8),
                             border_top_left_radius=12, border_top_right_radius=12)
            num = self.f_title.render(str(p["id"]), True, TEXT)
            surface.blit(num, num.get_rect(center=(rect.centerx, rect.y + 46)))
            lvl = self.f_small.render(p["level"], True, SUBTLE)
            surface.blit(lvl, lvl.get_rect(center=(rect.centerx, rect.y + 74)))
            best = best_scores.get(p["id"])
            tag = f"Best {best}" if best is not None else f"Par {p['min_moves']}"
            t = self.f_small.render(tag, True, (130, 200, 150) if best else SUBTLE)
            surface.blit(t, t.get_rect(center=(rect.centerx, rect.y + 94)))

    def hit(self, pos):
        for rect, idx in self.cards:
            if rect.collidepoint(pos):
                return idx
        return None
