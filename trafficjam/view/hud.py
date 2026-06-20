"""Heads-up display: title, move counter, undo button and move log."""
from __future__ import annotations

import pygame

PANEL = (28, 30, 38)
TEXT = (236, 238, 244)
SUBTLE = (150, 154, 166)
BTN = (66, 110, 180)
BTN_DISABLED = (70, 72, 80)
BTN_HOVER = (86, 134, 210)
LOG_BG = (20, 22, 28)


class Button:
    def __init__(self, rect, label):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.enabled = True

    def draw(self, surface, font, mouse):
        hover = self.rect.collidepoint(mouse) and self.enabled
        color = BTN_HOVER if hover else (BTN if self.enabled else BTN_DISABLED)
        pygame.draw.rect(surface, color, self.rect, border_radius=8)
        txt = font.render(self.label, True, TEXT if self.enabled else SUBTLE)
        surface.blit(txt, txt.get_rect(center=self.rect.center))

    def hit(self, pos):
        return self.enabled and self.rect.collidepoint(pos)


class Hud:
    def __init__(self, screen_w, screen_h, fonts):
        self.w = screen_w
        self.h = screen_h
        self.f_title = fonts["title"]
        self.f_body = fonts["body"]
        self.f_small = fonts["small"]
        self.f_mono = fonts["mono"]
        self.undo = Button((20, 70, 120, 40), "Undo")
        self.reset = Button((150, 70, 120, 40), "Reset")
        self.menu = Button((screen_w - 130, 70, 110, 40), "Levels")

    def draw(self, surface, *, level, move_count, par, move_log, mouse,
             can_undo):
        # Top banner.
        pygame.draw.rect(surface, PANEL, (0, 0, self.w, 60))
        title = self.f_title.render("TRAFFIC JAM", True, TEXT)
        surface.blit(title, (20, 14))
        lvl = self.f_body.render(f"Level {level}", True, SUBTLE)
        surface.blit(lvl, (self.w / 2 - lvl.get_width() / 2, 18))

        counter = self.f_body.render(
            f"Moves: {move_count}    Par: {par}", True, TEXT
        )
        surface.blit(counter, (self.w - counter.get_width() - 20, 20))

        self.undo.enabled = can_undo
        for b in (self.undo, self.reset, self.menu):
            b.draw(surface, self.f_body, mouse)

        self._draw_log(surface, move_log)

    def _draw_log(self, surface, move_log):
        h = 52
        y = self.h - h
        pygame.draw.rect(surface, LOG_BG, (0, y, self.w, h))
        label = self.f_small.render("MOVE LOG", True, SUBTLE)
        surface.blit(label, (20, y + 6))
        text = " ".join(move_log) if move_log else "—"
        # Keep the most recent moves visible if the line is long.
        rendered = self.f_mono.render(text, True, (130, 220, 150))
        if rendered.get_width() > self.w - 130:
            # right-align (show the tail)
            surface.blit(rendered, (self.w - 20 - rendered.get_width(), y + 24))
        else:
            surface.blit(rendered, (110, y + 24))
