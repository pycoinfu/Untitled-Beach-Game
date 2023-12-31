import json

import pygame

from engine._types import EventInfo
from engine.animations import FadeTransition
from engine.asset_loader import load_assets
from engine.background import ParallaxBackground
from engine.button import Button
from engine.camera import Camera
from engine.enums import GameStates
from engine.particles import FadingOutText
from engine.tilemap import TileLayerMap
from engine.utils import get_neighboring_tiles, pixel_to_tile, render_outline_text
from src.common import DATA_PATH, FADE_SPEED, FONT_PATH, HEIGHT, WIDTH
from src.npc import ItemNPC, QuestGiverNPC, QuestReceiverNPC, TalkingNPC
from src.player import Player


class GameInit:
    def __init__(self):
        self.assets = load_assets("game")
        self.player = Player(self.assets)

        self.tilemap = TileLayerMap("assets/map/map.tmx")
        self.map = self.tilemap.make_map()

        self.scroll = pygame.Vector2(self.player.rect.center)
        self.camera = Camera(WIDTH, HEIGHT)

        # triggers the state switch
        self.next_state = None
        # decides which state is next,
        # but doesn't trigger the state switch
        self._next_state = None
        self.exit = False

    def save(self):
        self.player.dump_save()

    def update(self, event_info: EventInfo):
        pass

    def draw(self, screen: pygame.Surface, event_info: EventInfo):
        pass


class BackgroundStage(GameInit):
    def __init__(self):
        super().__init__()

        self.suburb_background = ParallaxBackground(
            [
                (self.assets["bg0"], 0.025),
                (self.assets["bg1"], 0.075),
                (self.assets["bg2"], 0.15),
            ]
        )
        self.downtown_background = ParallaxBackground(
            [
                (self.assets["bg0"], 0.025),
                (self.assets["bg1"], 0.075),
                (self.assets["bg4"], 0.2),
            ]
        )
        self.beach_background = ParallaxBackground(
            [
                (self.assets["bg0"], 0.025),
                (self.assets["bg1"], 0.075),
                (self.assets["bg5"], 0.2),
            ]
        )

        self.background = self.suburb_background

    def update(self, event_info: EventInfo):
        super().update(event_info)

        if self.player.rect.x <= 124.5 * 16:
            self.background = self.suburb_background
        elif self.player.rect.x <= 283 * 16 and self.player.rect.y > 4 * 16:
            self.background = self.downtown_background
        elif self.player.rect.x >= 283 * 16:
            self.background = self.beach_background

    def draw(self, screen: pygame.Surface, event_info: EventInfo):
        super().draw(screen, event_info)

        self.background.draw(screen, self.camera.scroll)


class TileStage(BackgroundStage):
    def collisions(self, entity, event_info: EventInfo):
        collidable_tiles = get_neighboring_tiles(
            self.tilemap, 3, pixel_to_tile(entity.rect)
        )
        # for tile in collidable_tiles:
        #     pygame.draw.rect(pygame.display.get_surface(), "red", tile, 1)
        # pygame.draw.rect(pygame.display.get_surface(), "green", entity.rect, 1)

        entity.rect.x += entity.vel.x * event_info["dt"]

        for tile in collidable_tiles:
            if entity.rect.colliderect(tile):
                if entity.vel.x > 0:
                    entity.rect.right = tile.left
                elif entity.vel.x < 0:
                    entity.rect.left = tile.right

        entity.rect.y += entity.vel.y * event_info["dt"]

        for tile in collidable_tiles:
            if entity.rect.colliderect(tile):
                if entity.vel.y > 0:
                    entity.rect.bottom = tile.top
                    entity.jumping = False
                    entity.vel.y = 0
                elif entity.vel.y < 0:
                    entity.rect.top = tile.bottom
                    entity.vel.y = 0

        # disables mid-air jumps
        if entity.vel.y > 0:
            entity.jumping = True

    def update(self, event_info: EventInfo):
        super().update(event_info)

    def draw(self, screen: pygame.Surface, event_info: EventInfo):
        super().draw(screen, event_info)

        screen.blit(self.map, -self.camera.scroll)


class NPCStage(TileStage):
    def __init__(self):
        super().__init__()

        self.npcs = set()
        npc_types = {
            "talking_npc": TalkingNPC,
            "quest_giver_npc": QuestGiverNPC,
            "quest_receiver_npc": QuestReceiverNPC,
            "item_npc": ItemNPC,
        }
        for obj in self.tilemap.tilemap.get_layer_by_name("npcs"):
            npc_type = npc_types[obj.type]
            self.npcs.add(npc_type(self.assets, obj))

    def update(self, event_info: EventInfo):
        super().update(event_info)

        for npc in self.npcs:
            npc.update(event_info, self.player)

    def draw(self, screen: pygame.Surface, event_info: EventInfo):
        super().draw(screen, event_info)

        for npc in self.npcs:
            npc.draw(screen, self.camera, event_info)


class PlayerStage(NPCStage):
    def update(self, event_info: EventInfo):
        self.player.new_quest = False
        super().update(event_info)
        super().collisions(self.player, event_info)

        self.player.update(event_info)
        if not self.player.alive:
            self._next_state = GameStates.GAME

    def draw(self, screen: pygame.Surface, event_info: EventInfo):
        super().draw(screen, event_info)

        self.player.draw(screen, self.camera, event_info)


class CheckpointStage(PlayerStage):
    def __init__(self):
        super().__init__()

        self.checkpoints = []
        for obj in self.tilemap.tilemap.get_layer_by_name("checkpoints"):
            self.checkpoints.append(pygame.Rect(obj.x, obj.y, obj.width, obj.height))

    def update(self, event_info: EventInfo):
        super().update(event_info)

        for checkpoint in self.checkpoints:
            if checkpoint.colliderect(self.player.rect):
                # using checkpoint.x instead of self.player.rect.x
                # because if we do the latter the player would spawn
                # at an edge of a tile, which isn't ideal
                self.player.settings["checkpoint_pos"] = (
                    checkpoint.x,
                    self.player.rect.y,
                )


class CameraStage(CheckpointStage):
    def update(self, event_info: EventInfo):
        super().update(event_info)

        self.camera.adjust_to(event_info["dt"], self.player.rect)


class UIStage(CameraStage):
    def __init__(self):
        super().__init__()

        self.text_particles = []

        self.seashell_icon = self.assets["seashell"]
        self.seashell_font = pygame.Font(FONT_PATH, 8)
        self.last_amount = self.player.settings["seashells"]
        self.seashell_text = render_outline_text(
            str(self.last_amount), self.seashell_font, "white"
        )[0]

        seashell_icon_rect = self.seashell_icon.get_rect(bottomleft=(2, HEIGHT - 2))
        self.seashell_icon_pos = seashell_icon_rect.topleft
        self.seashell_text_pos = self.seashell_text.get_rect(
            midleft=(seashell_icon_rect.right + 2, seashell_icon_rect.centery)
        )

        # quest notifications
        self.new_quest_surf = render_outline_text(
            "New quest!", self.seashell_font, "white"
        )[0]
        bottomright = (WIDTH - 2, HEIGHT)
        self.new_quest_pos = self.new_quest_surf.get_rect(
            bottomright=bottomright
        ).topleft

        self.quest_finished_surf = render_outline_text(
            "Quest finished!", self.seashell_font, "white"
        )[0]
        bottomright = (WIDTH - 2, HEIGHT)
        self.quest_finished_pos = self.quest_finished_surf.get_rect(
            bottomright=bottomright
        ).topleft

        self.no_seashells_surf = render_outline_text(
            "Not enough seashells!", self.seashell_font, "white"
        )[0]
        bottomright = (WIDTH - 2, HEIGHT)
        self.no_seashells_pos = self.no_seashells_surf.get_rect(
            bottomright=bottomright
        ).topleft

        self.congrats_surf = render_outline_text(
            "You made it!", self.seashell_font, "white"
        )[0]
        bottomright = (WIDTH - 2, HEIGHT)
        self.congrats_pos = self.congrats_surf.get_rect(bottomright=bottomright).topleft

    def update(self, event_info: EventInfo):
        super().update(event_info)

        amount = self.player.settings["seashells"]
        # if the amount of seashells changed
        # this is done so that we don't render text every frame
        if amount != self.last_amount:
            self.seashell_text, self.seashell_text_darkener = render_outline_text(
                str(amount), self.seashell_font, "white"
            )
            self.last_amount = amount

            self.text_particles.append(
                FadingOutText(
                    self.quest_finished_surf.copy(), self.quest_finished_pos, 3, 230
                )
            )

        # quest notifications
        if self.player.new_quest:
            self.text_particles.append(
                FadingOutText(self.new_quest_surf.copy(), self.new_quest_pos, 3, 230)
            )

        for particle in self.text_particles:
            particle.update(event_info["dt"])

    def draw(self, screen: pygame.Surface, event_info: EventInfo):
        super().draw(screen, event_info)

        screen.blit(self.seashell_icon, self.seashell_icon_pos)
        screen.blit(self.seashell_text, self.seashell_text_pos)

        for particle in self.text_particles:
            particle.draw(screen)

            if not particle.alive:
                self.text_particles.remove(particle)


class BeachStage(UIStage):
    def __init__(self):
        super().__init__()

        self.player_congratulated = False

    def update(self, event_info: EventInfo):
        super().update(event_info)

        if (
            self.player.rect.x > 290 * 16
            and self.player.settings["seashells"] < 5
            and self.player.vel.x > 0
        ):
            self.player.vel.x = 0

            if len(self.text_particles) < 3:
                self.text_particles.append(
                    FadingOutText(
                        self.no_seashells_surf.copy(), self.no_seashells_pos, 5, 230
                    )
                )
        elif (
            int(self.player.rect.x) == 290 * 16
            and self.player.settings["seashells"] >= 5
            and not self.player_congratulated
        ):
            self.player_congratulated = True
            self.text_particles.append(
                FadingOutText(self.congrats_surf.copy(), self.congrats_pos, 3, 230)
            )

            # end the game!!
            self._next_state = GameStates.CREDITS
            self.transition.fade_speed /= 10

            with open(DATA_PATH, "w") as f:
                settings = json.dumps(
                    {
                        "run_intro": False,
                        "game_complete": True,
                    },
                    indent=4,
                )
                f.write(settings)

            pygame.mixer.music.fadeout(11000)


class PauseStage(BeachStage):
    def __init__(self):
        super().__init__()

        self.darkener = pygame.Surface((WIDTH, HEIGHT))
        self.darkener.set_alpha(150)

        self.last_frame: pygame.Surface = None
        self.pause_active = False

        # placeholder buttons
        button_colors = {
            "static": (109, 117, 141),
            "hover": (139, 147, 175),
            "text": (6, 6, 8),
        }
        size = pygame.Vector2(64, 16)
        button_texts = ("save & exit", "main menu", "continue")
        self.buttons = [
            Button(
                self.assets,
                (WIDTH - size.x - 10, HEIGHT - size.y * (i + 1) - 5 * (i + 1)),
                (size.x, size.y),
                button_colors,
                text,
                4,
            )
            for i, text in enumerate(button_texts)
        ]

    def update(self, event_info: EventInfo):
        if not self.pause_active:
            super().update(event_info)

        for event in event_info["events"]:
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.pause_active = not self.pause_active
                    if not self.pause_active:
                        self.last_frame = None

        if self.pause_active:
            for button in self.buttons:
                button.update(event_info)

                if button.clicked:
                    if button.text == "save & exit":
                        self.exit = True
                    elif button.text == "continue":
                        self.pause_active = False
                        self.last_frame = None
                    elif button.text == "main menu":
                        self._next_state = GameStates.MENU

    def draw(self, screen: pygame.Surface, event_info: EventInfo):
        super().draw(screen, event_info)

        if self.pause_active:
            if self.last_frame is None:
                self.last_frame = screen.copy()

            screen.blit(self.last_frame, (0, 0))
            screen.blit(self.darkener, (0, 0))

            for button in self.buttons:
                button.draw(screen)


class OSTStage(PauseStage):
    def __init__(self, ost_pos: float):
        super().__init__()

        self.ost = self.assets["ost"]
        self.ost_pos = ost_pos
        self.start_ost(self.ost)
        pygame.mixer.music.set_volume(0.4)

    def start_ost(self, ost):
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
        pygame.mixer.music.load(ost)
        pygame.mixer.music.play(-1)
        pygame.mixer.music.rewind()
        pygame.mixer.music.set_pos(self.ost_pos / 1000)

    def update(self, event_info: EventInfo):
        super().update(event_info)

        if self.pause_active and self.ost == self.assets["ost"]:
            self.ost = self.assets["ost_quiet"]
            self.ost_pos += pygame.mixer.music.get_pos()
            self.start_ost(self.ost)
            pygame.mixer.music.set_volume(0.7)

        elif not self.pause_active and self.ost == self.assets["ost_quiet"]:
            self.ost = self.assets["ost"]
            self.ost_pos += pygame.mixer.music.get_pos()
            self.start_ost(self.ost)
            pygame.mixer.music.set_volume(0.4)


class TransitionStage(OSTStage):
    def __init__(self, ost_pos: float):
        super().__init__(ost_pos)

        self.transition = FadeTransition(True, FADE_SPEED, (WIDTH, HEIGHT))

    def update(self, event_info: EventInfo):
        super().update(event_info)

        self.transition.update(event_info["dt"])
        if self._next_state is not None:
            self.transition.fade_in = False
            if self.transition.event:
                self.save()

                # get last ost position
                self.ost_pos += pygame.mixer.music.get_pos()
                pygame.mixer.music.stop()
                pygame.mixer.music.unload()

                self.next_state = self._next_state

    def draw(self, screen: pygame.Surface, event_info: EventInfo):
        super().draw(screen, event_info)

        self.transition.draw(screen)


class GameState(TransitionStage):
    pass
