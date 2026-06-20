"""Fireworks particle system for the win celebration."""
from __future__ import annotations

import math
import random

import pygame

GRAVITY = 240.0  # px / s^2
BURST_COLORS = [
    (255, 90, 90), (255, 200, 60), (110, 220, 130),
    (90, 170, 255), (220, 130, 240), (255, 255, 255),
]


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "max_life", "color", "size")

    def __init__(self, x, y, vx, vy, life, color, size):
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.life = life
        self.max_life = life
        self.color = color
        self.size = size

    def update(self, dt):
        self.vy += GRAVITY * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        self.life -= dt

    @property
    def alive(self):
        return self.life > 0


class Fireworks:
    def __init__(self, width, height):
        self.w = width
        self.h = height
        self.particles: list[Particle] = []
        self._spawn_timer = 0.0
        self._elapsed = 0.0

    def _burst(self, x, y):
        color = random.choice(BURST_COLORS)
        n = random.randint(28, 44)
        speed = random.uniform(120, 220)
        for i in range(n):
            ang = (i / n) * math.tau + random.uniform(-0.1, 0.1)
            spd = speed * random.uniform(0.6, 1.0)
            self.particles.append(Particle(
                x, y, math.cos(ang) * spd, math.sin(ang) * spd,
                life=random.uniform(0.8, 1.6), color=color,
                size=random.randint(2, 4),
            ))

    def update(self, dt):
        self._elapsed += dt
        self._spawn_timer -= dt
        if self._spawn_timer <= 0 and self._elapsed < 6.0:
            self._spawn_timer = random.uniform(0.25, 0.55)
            self._burst(random.uniform(self.w * 0.2, self.w * 0.8),
                        random.uniform(self.h * 0.2, self.h * 0.5))
        for p in self.particles:
            p.update(dt)
        self.particles = [p for p in self.particles if p.alive]

    def draw(self, surface):
        s = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
        for p in self.particles:
            a = max(0, min(255, int(255 * (p.life / p.max_life))))
            pygame.draw.circle(s, (*p.color, a), (int(p.x), int(p.y)), p.size)
        surface.blit(s, (0, 0))
