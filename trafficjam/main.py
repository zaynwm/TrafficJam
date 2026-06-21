"""Traffic Jam — entry point and game-state machine (menu / play / win)."""
from __future__ import annotations

import sys

import pygame

from trafficjam.data.puzzles import list_puzzles, load_puzzle
from trafficjam.controller.input import DragController
from trafficjam.view.hud import Hud
from trafficjam.view.iso import fit_projector
from trafficjam.view.menu import Menu
from trafficjam.view.particles import Fireworks
from trafficjam.model.moves import Move
from trafficjam.view.render import draw_board
from trafficjam.view.summary import Summary, score_for
from trafficjam.view.vehicles_draw import clear_mesh_cache

SCREEN_W, SCREEN_H = 980, 760
BG = (24, 26, 34)
MOVE_ANIM_DUR = 0.13
WIN_ANIM_DUR = 0.45


def load_fonts():
    pygame.font.init()
    return {
        "title": pygame.font.SysFont("arialroundedmtbold,arial", 30, bold=True),
        "body": pygame.font.SysFont("arial", 20),
        "small": pygame.font.SysFont("arial", 14),
        "mono": pygame.font.SysFont("menlo,consolas,courier", 16),
        "label": pygame.font.SysFont("arial", 16, bold=True),
    }


class Animation:
    def __init__(self, vid, dx, dy, dur, win=False):
        self.vid = vid
        self.dx = dx
        self.dy = dy
        self.dur = dur
        self.t = 0.0
        self.win = win

    def update(self, dt):
        self.t += dt
        return self.t >= self.dur

    def offset(self):
        p = min(1.0, self.t / self.dur)
        # ease-out
        p = 1 - (1 - p) * (1 - p)
        return (self.dx * (1 - p), self.dy * (1 - p))


class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((SCREEN_W, SCREEN_H))
        pygame.display.set_caption("Traffic Jam")
        self.clock = pygame.time.Clock()
        self.fonts = load_fonts()

        self.puzzles = [load_puzzle(p) for p in list_puzzles()]
        if not self.puzzles:
            raise SystemExit("No puzzles found in puzzles/")
        self.best_scores: dict[int, int] = {}

        self.menu = Menu(SCREEN_W, SCREEN_H, self.fonts, self.puzzles)
        self.hud = Hud(SCREEN_W, SCREEN_H, self.fonts)
        self.summary = Summary(SCREEN_W, SCREEN_H, self.fonts)

        self.state = "menu"
        self.index = 0
        self.board = None
        self.proj = None
        self.controller = None
        self.history: list[tuple[str, int, int]] = []
        self.move_log: list[str] = []
        self.anim: Animation | None = None
        self.fireworks: Fireworks | None = None

    # -- level lifecycle --------------------------------------------------
    def load_level(self, idx):
        self.index = idx
        clear_mesh_cache()
        data = self.puzzles[idx]
        self.board = data["board"].clone()
        self.proj = fit_projector(self.board.rows, self.board.cols,
                                  SCREEN_W, SCREEN_H, top_margin=150)
        self.controller = DragController(self.proj)
        self.history.clear()
        self.move_log.clear()
        self.anim = None
        self.fireworks = None
        self.state = "play"

    @property
    def par(self):
        return self.puzzles[self.index]["min_moves"]

    # -- moves ------------------------------------------------------------
    def apply_move(self, move, animate=True):
        v = self.board.vehicles[move.vehicle_id]
        prev = (v.id, v.row, v.col)
        # start offset = (old - new) so it slides from old position
        r0o, c0o = v.row, v.col
        self.board.apply(move)
        nv = self.board.vehicles[v.id]
        win = self.board.solved()

        # Coalesce with the immediately-preceding move of the same vehicle: the
        # log shows one token, the move count / score count it once, and undo
        # reverts the whole run. A net-zero pair counts as no move at all.
        if self.history and self.history[-1][0] == v.id:
            _, gr, gc = self.history[-1]          # group-start (before the run)
            if (nv.row, nv.col) == (gr, gc):
                self.history.pop()
                self.move_log.pop()
            else:
                if nv.horizontal:
                    direction, dist = ("R", nv.col - gc) if nv.col > gc else ("L", gc - nv.col)
                else:
                    direction, dist = ("D", nv.row - gr) if nv.row > gr else ("U", gr - nv.row)
                self.move_log[-1] = Move(v.id, direction, dist).token()
        else:
            self.history.append(prev)
            self.move_log.append(move.token())

        if animate:
            old_px = self.proj.point(r0o, c0o)
            new_px = self.proj.point(nv.row, nv.col)
            dx, dy = old_px[0] - new_px[0], old_px[1] - new_px[1]
            self.anim = Animation(v.id, dx, dy,
                                  WIN_ANIM_DUR if win else MOVE_ANIM_DUR, win=win)
        else:
            # A completed drag is already at its destination — no slide.
            self.anim = None
            if win:
                self.finish_win()

    def undo(self):
        if not self.history or self.anim:
            return
        vid, r, c = self.history.pop()
        v = self.board.vehicles[vid]
        from dataclasses import replace
        self.board.vehicles[vid] = replace(v, row=r, col=c)
        self.move_log.pop()

    def finish_win(self):
        self.state = "win"
        self.fireworks = Fireworks(SCREEN_W, SCREEN_H)
        score, _ = score_for(len(self.move_log), self.par)
        pid = self.puzzles[self.index]["id"]
        if score > self.best_scores.get(pid, -1):
            self.best_scores[pid] = score

    # -- main loop --------------------------------------------------------
    def run(self):
        while True:
            dt = self.clock.tick(60) / 1000.0
            self.handle_events()
            self.update(dt)
            self.draw()
            pygame.display.flip()

    def handle_events(self):
        mouse = pygame.mouse.get_pos()
        for e in pygame.event.get():
            if e.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if e.type == pygame.KEYDOWN:
                if e.key == pygame.K_ESCAPE:
                    self.state = "menu"
                if e.key == pygame.K_u and self.state == "play":
                    self.undo()
            if self.state == "menu":
                if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    idx = self.menu.hit(e.pos)
                    if idx is not None:
                        self.load_level(idx)
            elif self.state == "play":
                self._play_events(e, mouse)
            elif self.state == "win":
                self._win_events(e)

    def _play_events(self, e, mouse):
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.hud.undo.hit(e.pos):
                self.undo(); return
            if self.hud.reset.hit(e.pos):
                self.load_level(self.index); return
            if self.hud.menu.hit(e.pos):
                self.state = "menu"; return
            if self.anim is None:
                self.controller.on_press(self.board, e.pos)
        elif e.type == pygame.MOUSEMOTION:
            if self.anim is None:
                self.controller.on_motion(self.board, e.pos)
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            if self.anim is None and self.controller.dragging_id:
                move, is_click = self.controller.on_release(self.board, e.pos)
                if move is not None:
                    self.apply_move(move, animate=is_click)

    def _win_events(self, e):
        if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            if self.summary.replay_btn.hit(e.pos):
                self.load_level(self.index)
            elif self.summary.next_btn.hit(e.pos) and \
                    self.index + 1 < len(self.puzzles):
                self.load_level(self.index + 1)

    def update(self, dt):
        if self.anim is not None:
            if self.anim.update(dt):
                win = self.anim.win
                self.anim = None
                if win:
                    self.finish_win()
        if self.fireworks is not None:
            self.fireworks.update(dt)

    def draw(self):
        self.screen.fill(BG)
        mouse = pygame.mouse.get_pos()
        if self.state == "menu":
            self.menu.draw(self.screen, mouse, self.best_scores)
            return

        drag_off = drag_id = None
        anim_off = anim_id = None
        if self.anim is not None:
            anim_id, anim_off = self.anim.vid, self.anim.offset()
        elif self.controller and self.controller.dragging_id:
            drag_id = self.controller.dragging_id
            drag_off = self.controller.drag_offset(self.board)

        # label only the vehicle under the cursor, or the one being dragged
        label_id = None
        if self.controller:
            label_id = (self.controller.dragging_id
                        or self.controller.vehicle_at(self.board, mouse))

        draw_board(self.screen, self.proj, self.board,
                   selected_id=self.controller.selected_id if self.controller else None,
                   label_id=label_id, font=self.fonts["label"],
                   drag_offset=anim_off or drag_off,
                   drag_id=anim_id or drag_id)

        self.hud.draw(self.screen, level=self.puzzles[self.index]["id"],
                      move_count=len(self.move_log), par=self.par,
                      move_log=self.move_log, mouse=mouse,
                      can_undo=bool(self.history) and self.anim is None)

        if self.state == "win":
            if self.fireworks:
                self.fireworks.draw(self.screen)
            self.summary.draw(self.screen, player_moves=len(self.move_log),
                              par=self.par, mouse=mouse,
                              has_next=self.index + 1 < len(self.puzzles))


def main():
    Game().run()


if __name__ == "__main__":
    main()
