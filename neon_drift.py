"""
Neon Drift - Multi-orbita (Kepler) + fotones que expiran (rendezvous) con un solo boton.
Un boton (ESPACIO): toque = salto al anillo siguiente (wrap); mantener = elegir cualquiera.
Vulnerable durante el salto. Fotones cian con zona de atraccion invisible para perdonar el "casi".
Progresion por fotones recogidos. Meteoritos en llamas, muerte con estallido, Fin del Juego.
"""
import json
import math
import os
import random
from collections import deque
from pathlib import Path

import pygame
from pygame.math import Vector2

TAU = 2 * math.pi

# ---------------------------------------------------------------------------
# Config (todo lo ajustable vive aqui)
# ---------------------------------------------------------------------------
WIDTH, HEIGHT = 800, 800
FPS = 60
BG_COLOR = (5, 6, 12)
CENTER = (WIDTH // 2, HEIGHT // 2)

# Orbitas y fisica de Kepler: omega(r) = sqrt(GM / r^3). GM es la perilla maestra.
ORBIT_RADII = [120, 195, 270]
N_RINGS = len(ORBIT_RADII)
GM = 1900.0
ORBIT_GUIDE_COLOR = (26, 31, 48)
RING_CURRENT_COLOR = (60, 75, 110)
RING_TARGET_COLOR = (110, 215, 255)

# Salto / seleccion (un solo boton)
# Toque corto = salto al anillo siguiente hacia afuera (con wrap N-1 -> 0).
# Mantener = el destino recorre los demas anillos; soltar salta al resaltado.
JUMP_FRAMES = 11               # ~0.18s de tween entre anillos
SELECT_STEP_FRAMES = 21        # ~0.35s por anillo mientras se mantiene

SUN_RADIUS = 32
SUN_COLOR = (255, 120, 40)
SUN_HOT = (255, 185, 95)
SUN_SPOTS = 7
SUN_PULSE_SPEED = 0.045
SUN_SPIN_SPEED = 0.012

PLAYER_RADIUS = 7
PLAYER_COLOR = (255, 255, 255)          # blanco a vida llena
PLAYER_LOW_COLOR = (255, 60, 60)        # rojo cuando queda poca vida (eje no-amarillo, lejos del foton ambar)
PLAYER_TRAIL = 12
PLAYER_MAX_HP = 3
IFRAME_FRAMES = 48                      # invulnerabilidad tras un golpe (~0.8s, parpadea)
PICKUP_GLOW_FRAMES = 30                 # destello del PJ al recoger (~0.5s)

# Fotones: salen del sol, orbitan su anillo, expiran. AMBAR + ROMBO para distinguirlos del PJ blanco.
PHOTON_COLOR = (255, 196, 64)      # ambar/dorado (eje azul-amarillo, legible en daltonismo comun)
PHOTON_RADIUS = 6
PHOTON_EMERGE_SPEED = 3.6          # px/frame hacia afuera
PHOTON_LIFETIME = 480              # frames orbitando antes de expirar (~8s)
PHOTON_WARN = 90                   # ultimos ~1.5s: se desvanece por completo y reaparece
PHOTON_INTERVAL = 150              # frames entre apariciones
PHOTON_MAX = 2                     # maximo en pantalla
PHOTON_PICKUP = 14                 # contacto directo de recogida
PHOTON_ATTRACT = 48                # zona INVISIBLE de atraccion (forgiveness; no se muestra ni se menciona)
PHOTON_HOMING_SPEED = 6.5          # px/frame con que el foton vuela al PJ al entrar en la zona (> vel. tangencial ~4)
PHOTONS_PER_LEVEL = 5              # fotones para subir de nivel

# Meteoritos: curva suave con TECHO de velocidad. La dificultad tardia viene de la densidad, no de
# velocidades imposibles. Rango por nivel = [nivel-1, nivel+1] acotado a [SPEED_FLOOR, SPEED_CAP].
METEOR_SPEED_CAP = 7.5             # techo absoluto: nunca imposible de esquivar saltando
METEOR_SPEED_FLOOR = 1.0
METEOR_SPAWN_BASE = 84
METEOR_SPAWN_MIN = 30
METEOR_TRAIL = 14
SPAWN_RADIUS = 600
DESPAWN_RADIUS = 680
METEOR_CAP_BASE = 6                # max en pantalla a nivel 1; sube +1 por nivel hasta el tope
METEOR_CAP_MAX = 14

DEATH_PARTICLES = 50
DEATH_PALETTE = [(255, 255, 255), (255, 180, 120), (255, 90, 70), (255, 225, 200)]

# Fondo: campo de estrellas estatico + asteroides apagados que derivan lentisimo (sensacion parallax).
STAR_COUNT = 110
DECO_ASTEROIDS = 3
DECO_DRIFT = (0.06, 0.22)          # px/frame: lentisimo
MENU_ASTEROIDS = 7                 # el menu lleva mas (no importa saturar) + meteoritos lejanos
MENU_BLUR = 0.34                   # 0..1: menor = mas desenfoque (downscale-upscale)

SAVE_PATH = Path(__file__).resolve().parent / "save.json"
STATE_MENU, STATE_TUTORIAL = "menu", "tutorial"
STATE_PLAYING, STATE_DYING, STATE_GAMEOVER = "playing", "dying", "gameover"
GAME_NAME = "KEPLER'S WAKE"


def omega(r):
    """Velocidad angular orbital (3a ley de Kepler)."""
    return math.sqrt(GM / (r * r * r))


def smoothstep(t):
    return t * t * (3 - 2 * t)


def lerp_color(c1, c2, t):
    t = max(0.0, min(1.0, t))
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def ring_pos(angle, r):
    return (CENTER[0] + math.cos(angle) * r, CENTER[1] + math.sin(angle) * r)


# ---------------------------------------------------------------------------
# Persistencia. Disenado para extraerse a storage.py en un solo movimiento.
# ---------------------------------------------------------------------------
class SaveManager:
    VERSION = 1
    DEFAULTS = {"version": VERSION, "level": 1, "score": 0, "best_score": 0, "tutorial_seen": False}

    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return dict(self.DEFAULTS)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            print(f"[save] archivo ilegible ({e}); reinicio con valores por defecto")
            self._backup_corrupt()
            return dict(self.DEFAULTS)
        return self._sanitize(raw)

    def save(self, data):
        payload = {
            "version": self.VERSION,
            "level": self._as_int(data.get("level"), 1, min_v=1),
            "score": self._as_int(data.get("score"), 0, min_v=0),
            "best_score": self._as_int(data.get("best_score"), 0, min_v=0),
            "tutorial_seen": bool(data.get("tutorial_seen", False)),
        }
        payload["best_score"] = max(payload["best_score"], payload["score"])
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            print(f"[save] no se pudo guardar ({e})")
            return False

    def _sanitize(self, raw):
        d = dict(self.DEFAULTS)
        if isinstance(raw, dict):
            d["level"] = self._as_int(raw.get("level"), 1, min_v=1)
            d["score"] = self._as_int(raw.get("score"), 0, min_v=0)
            d["best_score"] = self._as_int(raw.get("best_score"), 0, min_v=0)
            d["tutorial_seen"] = bool(raw.get("tutorial_seen", False))
        d["best_score"] = max(d["best_score"], d["score"])
        return d

    def _backup_corrupt(self):
        try:
            backup = self.path.with_name("save.corrupt.json")
            os.replace(self.path, backup)
            print(f"[save] copia del archivo danado en {backup.name}")
        except OSError:
            pass

    @staticmethod
    def _as_int(value, default, min_v=None):
        try:
            n = int(value)
        except (TypeError, ValueError):
            return default
        return max(min_v, n) if min_v is not None else n


# ---------------------------------------------------------------------------
# Render neon reutilizable.
# ---------------------------------------------------------------------------
def draw_glow(surface, color, center, radius, glow_factor=3.0, layers=10, brightness=1.0):
    glow_radius = int(radius * glow_factor)
    glow = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
    for i in range(layers, 0, -1):
        t = i / layers
        r = int(glow_radius * t)
        alpha = min(255, int((45 * (1 - t) ** 2 + 8) * brightness))
        pygame.draw.circle(glow, (*color, alpha), (glow_radius, glow_radius), r)
    surface.blit(glow, (center[0] - glow_radius, center[1] - glow_radius))
    pygame.draw.circle(surface, color, center, radius)


def add_blob(surface, color, pos, radius, alpha):
    r = max(1, int(radius))
    blob = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
    pygame.draw.circle(blob, (*color, alpha), (r, r), r)
    surface.blit(blob, (int(pos[0]) - r, int(pos[1]) - r), special_flags=pygame.BLEND_RGBA_ADD)


def draw_rings(surface, selecting, target_idx, current_idx):
    for i, r in enumerate(ORBIT_RADII):
        if selecting and i == target_idx and i != current_idx:
            pygame.draw.circle(surface, RING_TARGET_COLOR, CENTER, int(r), 3)   # anillo destino
        elif i == current_idx:
            pygame.draw.circle(surface, RING_CURRENT_COLOR, CENTER, int(r), 2)  # tu anillo
        else:
            pygame.draw.circle(surface, ORBIT_GUIDE_COLOR, CENTER, int(r), 1)   # guia tenue


def blur_surface(surf, factor=MENU_BLUR):
    """Desenfoque barato sin dependencias: downscale + upscale suave."""
    w, h = surf.get_size()
    sw, sh = max(1, int(w * factor)), max(1, int(h * factor))
    small = pygame.transform.smoothscale(surf, (sw, sh))
    return pygame.transform.smoothscale(small, (w, h))


def draw_glow_text(surface, text, font, center, color=(245, 250, 255),
                   glow=(120, 200, 255), spread=3, glow_alpha=46):
    base = font.render(text, True, glow)
    halo = pygame.Surface((base.get_width() + spread * 6, base.get_height() + spread * 6),
                          pygame.SRCALPHA)
    cx, cy = halo.get_width() // 2, halo.get_height() // 2
    for dx, dy in [(-spread, 0), (spread, 0), (0, -spread), (0, spread),
                   (-spread, -spread), (spread, spread), (spread, -spread), (-spread, spread)]:
        g = base.copy()
        g.set_alpha(glow_alpha)
        halo.blit(g, g.get_rect(center=(cx + dx, cy + dy)))
    surface.blit(halo, halo.get_rect(center=center))
    crisp = font.render(text, True, color)
    rect = crisp.get_rect(center=center)
    surface.blit(crisp, rect)
    return rect


def draw_diamond(surface, center, r, color, filled=True, glow=False):
    """Rombo (icono de foton). filled=False dibuja solo el contorno."""
    cx, cy = center
    pts = [(cx, cy - r * 1.4), (cx + r, cy), (cx, cy + r * 1.4), (cx - r, cy)]
    if glow:
        add_blob(surface, color, center, r * 1.2, 38)        # halo sutil, no domina
    if filled:
        pygame.draw.polygon(surface, color, pts)
        pygame.draw.polygon(surface, lerp_color(color, (255, 255, 255), 0.4), pts, 1)  # borde definido
        cr = r * 0.5                                          # nucleo brillante (gema)
        core = [(cx, cy - cr * 1.4), (cx + cr, cy), (cx, cy + cr * 1.4), (cx - cr, cy)]
        pygame.draw.polygon(surface, lerp_color(color, (255, 255, 255), 0.6), core)
    else:
        pygame.draw.polygon(surface, color, pts, 2)


def draw_demo_meteor(surface, pos, tail=(-1.0, -0.35), length=9, head_r=6):
    """Meteorito estatico pero con cola, como si se moviera (para el tutorial)."""
    d = Vector2(tail)
    if d.length():
        d = d.normalize()
    for i in range(length, 0, -1):
        t = i / length
        p = (pos[0] + d.x * i * 7, pos[1] + d.y * i * 7)
        col = lerp_color((255, 225, 90), (180, 30, 10), t)
        add_blob(surface, col, p, head_r * (1 - t) + 2, int(150 * (1 - t)))
    draw_glow(surface, (255, 90, 30), (int(pos[0]), int(pos[1])), head_r, glow_factor=2.6)
    pygame.draw.circle(surface, (255, 230, 160), (int(pos[0]), int(pos[1])), max(1, int(head_r * 0.55)))


# ---------------------------------------------------------------------------
# Fondo espacial: estrellas (estaticas, leve titileo) + asteroides apagados a la deriva.
# Es decorado puro: sin glow ni fuego, para no confundirse con meteoritos ni fotones.
# ---------------------------------------------------------------------------
class DecoAsteroid:
    """Roca gris-marron, opaca, derivando lentisimo. Solo ambiente."""
    def __init__(self):
        self.pos = Vector2(random.uniform(0, WIDTH), random.uniform(0, HEIGHT))
        a = random.uniform(0, TAU)
        self.vel = Vector2(math.cos(a), math.sin(a)) * random.uniform(*DECO_DRIFT)
        self.spin = random.uniform(-0.004, 0.004)
        self.rot = random.uniform(0, TAU)
        self.rad = random.uniform(16, 34)
        base = random.choice([(46, 44, 50), (52, 47, 42), (40, 42, 48)])
        self.color = base
        self.edge = tuple(max(0, c - 14) for c in base)
        n = random.randint(7, 10)
        self.shape = [(math.cos(i / n * TAU), math.sin(i / n * TAU),
                       random.uniform(0.72, 1.0)) for i in range(n)]
        self.craters = [(random.uniform(-0.4, 0.4), random.uniform(-0.4, 0.4),
                         random.uniform(0.12, 0.24)) for _ in range(random.randint(1, 3))]

    def update(self):
        self.pos += self.vel
        self.rot += self.spin
        m = self.rad + 6
        if self.pos.x < -m: self.pos.x = WIDTH + m
        if self.pos.x > WIDTH + m: self.pos.x = -m
        if self.pos.y < -m: self.pos.y = HEIGHT + m
        if self.pos.y > HEIGHT + m: self.pos.y = -m

    def draw(self, surface):
        c, s = math.cos(self.rot), math.sin(self.rot)
        pts = []
        for vx, vy, vr in self.shape:
            x, y = vx * vr * self.rad, vy * vr * self.rad
            pts.append((self.pos.x + x * c - y * s, self.pos.y + x * s + y * c))
        pygame.draw.polygon(surface, self.color, pts)
        pygame.draw.polygon(surface, self.edge, pts, 1)
        for cx, cy, cr in self.craters:
            x, y = cx * self.rad, cy * self.rad
            pos = (int(self.pos.x + x * c - y * s), int(self.pos.y + x * s + y * c))
            pygame.draw.circle(surface, self.edge, pos, max(1, int(cr * self.rad)))


class Starfield:
    def __init__(self, n_asteroids=DECO_ASTEROIDS, distant_meteors=False):
        self.stars = []
        for _ in range(STAR_COUNT):
            bright = random.random() < 0.18
            self.stars.append({
                "pos": (random.randint(0, WIDTH), random.randint(0, HEIGHT)),
                "size": 2 if bright else 1,
                "base": random.randint(120, 200) if bright else random.randint(40, 90),
                "tw": random.random() < 0.25,
                "phase": random.uniform(0, TAU),
            })
        self.asteroids = [DecoAsteroid() for _ in range(n_asteroids)]
        self.distant = distant_meteors
        self.dmeteors = []
        self.dtimer = random.randint(30, 90)
        self.t = 0

    def _spawn_distant(self):
        edge = random.choice("tblr")
        if edge == "t": pos = Vector2(random.uniform(0, WIDTH), -20)
        elif edge == "b": pos = Vector2(random.uniform(0, WIDTH), HEIGHT + 20)
        elif edge == "l": pos = Vector2(-20, random.uniform(0, HEIGHT))
        else: pos = Vector2(WIDTH + 20, random.uniform(0, HEIGHT))
        aim = Vector2(random.uniform(0, WIDTH), random.uniform(0, HEIGHT))
        vel = (aim - pos).normalize() * random.uniform(1.1, 2.0)
        return {"pos": pos, "vel": vel, "trail": deque(maxlen=10),
                "r": random.uniform(1.6, 2.8)}

    def update(self):
        self.t += 1
        for a in self.asteroids:
            a.update()
        if self.distant:
            self.dtimer -= 1
            if self.dtimer <= 0:
                self.dmeteors.append(self._spawn_distant())
                self.dtimer = random.randint(70, 150)
            for m in self.dmeteors:
                m["trail"].append((m["pos"].x, m["pos"].y))
                m["pos"] += m["vel"]
            self.dmeteors = [m for m in self.dmeteors
                             if -60 < m["pos"].x < WIDTH + 60 and -60 < m["pos"].y < HEIGHT + 60]

    def draw(self, surface):
        for st in self.stars:
            a = st["base"]
            if st["tw"]:
                a = int(a * (0.55 + 0.45 * (0.5 + 0.5 * math.sin(self.t * 0.05 + st["phase"]))))
            x, y = st["pos"]
            if st["size"] == 1:
                surface.fill((a, a, a), (x, y, 1, 1))
            else:
                dot = pygame.Surface((4, 4), pygame.SRCALPHA)
                pygame.draw.circle(dot, (a, a, a, a), (2, 2), 2)
                surface.blit(dot, (x - 2, y - 2))
        for m in self.dmeteors:                       # meteoritos lejanos, tenues
            n = len(m["trail"])
            for i, p in enumerate(m["trail"]):
                t = (i + 1) / n
                add_blob(surface, (150, 110, 80), p, m["r"] * (0.4 + 0.7 * t), int(60 * t))
            add_blob(surface, (190, 150, 110), (m["pos"].x, m["pos"].y), m["r"], 110)
        for ast in self.asteroids:
            ast.draw(surface)


# ---------------------------------------------------------------------------
# Sol vivo.
# ---------------------------------------------------------------------------
class Sun:
    def __init__(self, center, radius, color):
        self.center = center
        self.radius = radius
        self.color = color
        self.pulse = 0.0
        self.spin = 0.0
        self.spots = self._make_spots(SUN_SPOTS)

    def _make_spots(self, n):
        return [{
            "lat": random.uniform(-1.0, 1.0),
            "lon": random.uniform(0, TAU),
            "size": random.uniform(0.12, 0.26) * self.radius,
            "shade": random.uniform(-0.45, 0.55),
        } for _ in range(n)]

    def update(self):
        self.pulse += SUN_PULSE_SPEED
        self.spin += SUN_SPIN_SPEED

    def draw(self, surface):
        p = 0.5 + 0.5 * math.sin(self.pulse)
        core = lerp_color(self.color, SUN_HOT, 0.45 * p)
        draw_glow(surface, self.color, self.center, self.radius,
                  glow_factor=3.0 + 0.55 * p, brightness=0.85 + 0.4 * p)
        pygame.draw.circle(surface, core, self.center, self.radius)
        cx, cy = self.center
        for s in self.spots:
            lon = s["lon"] - self.spin
            cos_lon = math.cos(lon)
            if cos_lon <= 0.0:
                continue
            x = cx + self.radius * math.cos(s["lat"]) * math.sin(lon)
            y = cy + self.radius * math.sin(s["lat"])
            r = max(1, int(s["size"] * cos_lon))
            fade = min(1.0, cos_lon * 1.6)
            if s["shade"] >= 0:
                col = lerp_color(core, (255, 235, 200), s["shade"])
            else:
                col = lerp_color(core, (95, 38, 12), -s["shade"])
            spot = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(spot, (*col, int(200 * fade)), (r, r), r)
            surface.blit(spot, (int(x) - r, int(y) - r))


# ---------------------------------------------------------------------------
# Foton: emerge del sol -> se asienta en un anillo -> orbita (Kepler) -> expira.
# ---------------------------------------------------------------------------
class Photon:
    def __init__(self, ring_idx, angle):
        self.ring = ring_idx
        self.target_r = ORBIT_RADII[ring_idx]
        self.angle = angle
        self.r = SUN_RADIUS * 0.4
        self.state = "emerging"            # emerging -> orbiting -> homing
        self.life = PHOTON_LIFETIME
        self.trail = deque(maxlen=18)
        self._pos = None                   # posicion libre cuando va en homing
        self.no_expire = False             # foton de bienvenida: no expira hasta recogerse

    def update(self, player_pos):
        """Avanza un frame. Devuelve True si el PJ lo capturo este frame."""
        if self.state == "emerging":
            self.trail.append(self.pos)
            self.r += PHOTON_EMERGE_SPEED
            if self.r >= self.target_r:
                self.r = self.target_r
                self.state = "orbiting"
            return False

        if not self.no_expire:
            self.life -= 1
        if self.state == "orbiting":
            self.angle = (self.angle + omega(self.r)) % TAU   # orbita a la velocidad de su anillo
            if self._dist(player_pos) < PHOTON_ATTRACT:       # entra en la zona invisible -> homing
                self.state = "homing"
                self._pos = Vector2(ring_pos(self.angle, self.r))
        if self.state == "homing":
            to = Vector2(player_pos) - self._pos
            d = to.length()
            if d <= PHOTON_PICKUP:
                return True
            if d > 0:
                self._pos += to * (min(PHOTON_HOMING_SPEED, d) / d)
            self.trail.append((self._pos.x, self._pos.y))
        return False

    def _dist(self, point):
        x, y = self.pos
        return math.hypot(point[0] - x, point[1] - y)

    @property
    def catchable(self):
        return self.state in ("orbiting", "homing")

    @property
    def expired(self):
        return (not self.no_expire) and self.state != "emerging" and self.life <= 0

    @property
    def pos(self):
        if self.state == "homing":
            return (self._pos.x, self._pos.y)
        return ring_pos(self.angle, self.r)

    def _fade(self):
        """1.0 normal; en los ultimos PHOTON_WARN frames se desvanece a 0 y reaparece."""
        if not self.no_expire and self.state == "orbiting" and self.life < PHOTON_WARN:
            # ~3 ciclos completos en 1.5s: alpha llega a 0 (invisible) y vuelve a full.
            return 0.5 - 0.5 * math.cos(self.life * (TAU * 3 / PHOTON_WARN))
        return 1.0

    def draw(self, surface):
        pos = self.pos
        if self.state == "emerging":
            n = len(self.trail)
            for i, p in enumerate(self.trail):
                t = (i + 1) / n
                add_blob(surface, PHOTON_COLOR, p, 3 * t + 1, int(40 * t))   # rastro tenue
            self._draw_gem(surface, pos, 0.8)
            return
        if self.state == "homing":                                          # estela breve al ser atraido
            n = len(self.trail)
            for i, p in enumerate(self.trail):
                t = (i + 1) / n
                add_blob(surface, PHOTON_COLOR, p, 3 * t + 1, int(75 * t))
        self._draw_gem(surface, pos, 1.0, alpha=self._fade())

    def _draw_gem(self, surface, pos, scale=1.0, alpha=1.0):
        """Rombo ambar con halo, dibujado sobre superficie alpha para poder desvanecerse a 0."""
        if alpha <= 0.01:
            return
        R = int(PHOTON_RADIUS * 2.6 * scale) + 6
        gem = pygame.Surface((R * 2, R * 2), pygame.SRCALPHA)
        c = R
        for layer in range(5, 0, -1):                       # halo difuso
            t = layer / 5
            rad = int(PHOTON_RADIUS * 2.4 * scale * t)
            d = [(c, c - rad), (c + rad, c), (c, c + rad), (c - rad, c)]
            pygame.draw.polygon(gem, (*PHOTON_COLOR, int(34 * (1 - t) + 8)), d)
        rad = PHOTON_RADIUS * scale
        diamond = [(c, c - rad * 1.5), (c + rad, c), (c, c + rad * 1.5), (c - rad, c)]
        pygame.draw.polygon(gem, (*PHOTON_COLOR, 235), diamond)
        core = rad * 0.55
        pygame.draw.polygon(gem, (255, 245, 220, 255),
                            [(c, c - core * 1.5), (c + core, c), (c, c + core * 1.5), (c - core, c)])
        if alpha < 1.0:
            gem.set_alpha(int(255 * alpha))
        surface.blit(gem, (int(pos[0]) - c, int(pos[1]) - c))


class PhotonField:
    def __init__(self):
        self.photons = []
        self.timer = 0
        self.warmup = False

    def clear(self):
        self.photons.clear()
        self.timer = 0
        self.warmup = False

    def seed_intro(self, avoid_ring):
        """Inicio facil: un solo foton que no expira, en un anillo distinto al del jugador."""
        self.warmup = True
        ring = (avoid_ring + 1) % N_RINGS
        ph = Photon(ring, random.uniform(0, TAU))
        ph.no_expire = True
        self.photons = [ph]
        self.timer = 0

    def update(self, player_pos):
        """Avanza el campo y devuelve cuantos fotones capturo el PJ este frame."""
        if not self.warmup:
            self.timer -= 1
            if self.timer <= 0 and len(self.photons) < PHOTON_MAX:
                self.photons.append(Photon(random.randrange(N_RINGS), random.uniform(0, TAU)))
                self.timer = PHOTON_INTERVAL
        collected, keep = 0, []
        for p in self.photons:
            if p.update(player_pos):
                collected += 1
            elif not p.expired:
                keep.append(p)
        self.photons = keep
        return collected

    def draw(self, surface):
        for p in self.photons:
            p.draw(surface)


# ---------------------------------------------------------------------------
# Meteorito en llamas + spawner.
# ---------------------------------------------------------------------------
class Meteor:
    def __init__(self, pos, vel, radius):
        self.pos = Vector2(pos)
        self.vel = Vector2(vel)
        self.radius = radius
        self.trail = deque(maxlen=METEOR_TRAIL)

    def update(self):
        self.trail.append(Vector2(self.pos))
        self.pos += self.vel

    def offscreen(self):
        return self.pos.distance_to(Vector2(CENTER)) > DESPAWN_RADIUS

    def draw(self, surface):
        n = len(self.trail)
        for i, p in enumerate(self.trail):
            t = (i + 1) / n
            col = lerp_color((180, 30, 10), (255, 225, 90), t)
            add_blob(surface, col, p, self.radius * (0.5 + 0.9 * t), int(150 * t))
        head = (int(self.pos.x), int(self.pos.y))
        draw_glow(surface, (255, 90, 30), head, self.radius, glow_factor=2.6)
        pygame.draw.circle(surface, (255, 230, 160), head, max(1, int(self.radius * 0.55)))


class MeteorSpawner:
    def __init__(self):
        self.meteors = []
        self.timer = 0

    def clear(self):
        self.meteors.clear()
        self.timer = 0

    def update(self, level):
        self.timer -= 1
        if self.timer <= 0 and self._can_spawn(level):
            self.meteors.append(self._spawn(level))
            self.timer = max(METEOR_SPAWN_MIN, METEOR_SPAWN_BASE - 3 * (level - 1))
        for m in self.meteors:
            m.update()
        self.meteors = [m for m in self.meteors if not m.offscreen()]

    def _cap(self, level):
        return min(METEOR_CAP_MAX, METEOR_CAP_BASE + (level - 1))

    def _can_spawn(self, level):
        return len(self.meteors) < self._cap(level)

    def _spawn(self, level):
        angle = random.uniform(0, TAU)
        origin = Vector2(CENTER) + Vector2(math.cos(angle), math.sin(angle)) * SPAWN_RADIUS
        reach = ORBIT_RADII[-1]
        target = Vector2(CENTER) + Vector2(random.uniform(-reach, reach), random.uniform(-reach, reach))
        # Curva suave con techo: rango [nivel-1, nivel+1] acotado. Nunca imposible de esquivar.
        lo = max(METEOR_SPEED_FLOOR, min(level - 1.0, METEOR_SPEED_CAP - 1.0))
        hi = max(2.0, min(level + 1.0, METEOR_SPEED_CAP))
        speed = random.uniform(lo, hi)
        vel = (target - origin).normalize() * speed
        return Meteor(origin, vel, random.randint(5, 8))

    def remove_hits(self, point, radius):
        p = Vector2(point)
        hit = [m for m in self.meteors if p.distance_to(m.pos) < m.radius + radius]
        if hit:
            self.meteors = [m for m in self.meteors if m not in hit]
        return hit

    def hits(self, point, radius):
        p = Vector2(point)
        return any(p.distance_to(m.pos) < m.radius + radius for m in self.meteors)

    def draw(self, surface):
        for m in self.meteors:
            m.draw(surface)


# ---------------------------------------------------------------------------
# Particula geometrica (estallido de muerte y "pop" al recoger fotones).
# ---------------------------------------------------------------------------
class Particle:
    def __init__(self, pos, color, speed=(1.5, 7.5), size=(3.0, 7.0)):
        a = random.uniform(0, TAU)
        spd = random.uniform(*speed)
        self.pos = Vector2(pos)
        self.vel = Vector2(math.cos(a), math.sin(a)) * spd
        self.color = color
        self.life = 1.0
        self.decay = random.uniform(0.012, 0.026)
        self.size = random.uniform(*size)
        self.rot = random.uniform(0, TAU)
        self.spin = random.uniform(-0.25, 0.25)

    def update(self):
        self.pos += self.vel
        self.vel *= 0.96
        self.rot += self.spin
        self.life -= self.decay

    @property
    def dead(self):
        return self.life <= 0

    def draw(self, surface):
        alpha = max(0, int(210 * self.life))
        s = self.size * (0.4 + 0.6 * self.life)
        box = int(s * 2 + 4)
        c = box / 2
        surf = pygame.Surface((box, box), pygame.SRCALPHA)
        pts = [(c + math.cos(self.rot + k * math.pi / 2) * s,
                c + math.sin(self.rot + k * math.pi / 2) * s) for k in range(4)]
        pygame.draw.polygon(surf, (*self.color, alpha), pts)
        surface.blit(surf, (self.pos.x - c, self.pos.y - c), special_flags=pygame.BLEND_RGBA_ADD)


# ---------------------------------------------------------------------------
# Jugador: orbita Kepler con un solo boton (mantener barre, soltar salta).
# ---------------------------------------------------------------------------
class Player:
    def __init__(self, ring_index=0):
        self.ring_index = ring_index
        self.radius = ORBIT_RADII[ring_index]
        self.angle = 0.0
        self.trail = deque(maxlen=PLAYER_TRAIL)

        self.state = "on_ring"          # on_ring | jumping
        self.was_holding = False
        self.selecting = False
        self.select_frames = 0
        self.target_ring = ring_index
        # jump
        self.jump_t = 0.0
        self.jump_from_r = self.radius
        self.jump_to_r = self.radius
        self.jump_to_ring = ring_index
        # vida / feedback
        self.hp = PLAYER_MAX_HP
        self.iframes = 0
        self.glow_boost = 0

    def hit(self):
        """Recibe un golpe si no es invulnerable. Devuelve True si murio (hp<=0)."""
        if self.iframes > 0:
            return False
        self.hp -= 1
        self.iframes = IFRAME_FRAMES
        return self.hp <= 0

    def feed_boost(self):
        self.glow_boost = PICKUP_GLOW_FRAMES

    def hp_color(self):
        if self.hp >= PLAYER_MAX_HP:
            return PLAYER_COLOR
        t = (PLAYER_MAX_HP - self.hp) / max(1, PLAYER_MAX_HP - 1)
        return lerp_color(PLAYER_COLOR, PLAYER_LOW_COLOR, t)

    def _sweep_candidates(self):
        # Anillos distintos al actual, en orden hacia afuera con wrap (el toque = el primero).
        return [(self.ring_index + k) % N_RINGS for k in range(1, N_RINGS)]

    def _sweep_target(self):
        cands = self._sweep_candidates()
        step = self.select_frames // SELECT_STEP_FRAMES
        return cands[step % len(cands)]

    def _begin_jump(self, target):
        self.state = "jumping"
        self.jump_t = 0.0
        self.jump_from_r = self.radius
        self.jump_to_r = ORBIT_RADII[target]
        self.jump_to_ring = target
        self.select_frames = 0

    def _advance_jump(self):
        self.jump_t = min(1.0, self.jump_t + 1.0 / JUMP_FRAMES)
        self.radius = self.jump_from_r + (self.jump_to_r - self.jump_from_r) * smoothstep(self.jump_t)
        if self.jump_t >= 1.0:
            self.ring_index = self.jump_to_ring
            self.radius = ORBIT_RADII[self.ring_index]
            self.state = "on_ring"

    def update(self, space_held):
        if self.state == "jumping":
            self.selecting = False
            self._advance_jump()
        else:
            rising = space_held and not self.was_holding
            falling = (not space_held) and self.was_holding
            if rising:                              # al presionar el destino arranca en el contiguo
                self.select_frames = 0
                self.target_ring = self._sweep_target()
            elif space_held:                        # mantener: el destino recorre los otros anillos
                self.select_frames += 1
                self.target_ring = self._sweep_target()
            if falling:                             # soltar siempre salta (toque=contiguo, mantener=resaltado)
                self._begin_jump(self.target_ring)
            self.selecting = space_held and self.state == "on_ring"

        # El angulo avanza siempre a la omega del radio actual (tween incluido).
        self.angle = (self.angle + omega(self.radius)) % TAU
        self.was_holding = space_held
        if self.iframes > 0:
            self.iframes -= 1
        if self.glow_boost > 0:
            self.glow_boost -= 1

    @property
    def pos(self):
        return (int(CENTER[0] + math.cos(self.angle) * self.radius),
                int(CENTER[1] + math.sin(self.angle) * self.radius))

    def draw(self, surface):
        self.trail.append(self.pos)
        col = self.hp_color()
        jumping = self.state == "jumping"

        # Parpadeo de invulnerabilidad: se salta frames alternos tras un golpe.
        if self.iframes > 0 and (self.iframes // 4) % 2 == 0:
            return

        # Estela: mas larga y brillante durante el salto ("lanzarse entre orbitas").
        n = len(self.trail)
        trail_alpha = 200 if jumping else 110
        trail_scale = 0.95 if jumping else 0.6
        for i, (x, y) in enumerate(self.trail):
            t = (i + 1) / n
            r = max(1, int(PLAYER_RADIUS * trail_scale * t))
            dot = pygame.Surface((r * 2, r * 2), pygame.SRCALPHA)
            pygame.draw.circle(dot, (*col, int(trail_alpha * t)), (r, r), r)
            surface.blit(dot, (x - r, y - r))

        # Brillo: base, + destello al recoger, + pulso si la vida esta critica.
        glow = 3.0
        bright = 1.0
        if self.glow_boost > 0:
            k = self.glow_boost / PICKUP_GLOW_FRAMES
            glow += 1.6 * k
            bright += 0.9 * k
        if self.hp == 1:
            bright *= 0.8 + 0.35 * (0.5 + 0.5 * math.sin(pygame.time.get_ticks() * 0.012))
        draw_glow(surface, col, self.pos, PLAYER_RADIUS, glow_factor=glow, brightness=bright)


# ---------------------------------------------------------------------------
# Boton de UI.
# ---------------------------------------------------------------------------
class Button:
    def __init__(self, rect, label, on_click, accent=(120, 200, 255)):
        self.rect = pygame.Rect(rect)
        self.label = label
        self.on_click = on_click
        self.accent = accent

    def draw(self, surface, font, hover):
        bg = (40, 52, 80) if hover else (22, 28, 44)
        pygame.draw.rect(surface, bg, self.rect, border_radius=10)
        pygame.draw.rect(surface, self.accent, self.rect, width=2, border_radius=10)
        txt = font.render(self.label, True, (235, 240, 255))
        surface.blit(txt, txt.get_rect(center=self.rect.center))

    def click(self, pos):
        if self.rect.collidepoint(pos):
            self.on_click()
            return True
        return False


# ---------------------------------------------------------------------------
# Bucle principal + estados.
# ---------------------------------------------------------------------------
class Game:
    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        pygame.display.set_caption(GAME_NAME.title())
        self.clock = pygame.time.Clock()
        self.font = pygame.font.Font(None, 30)
        self.font_small = pygame.font.Font(None, 23)
        self.font_med = pygame.font.Font(None, 28)
        self.font_big = pygame.font.Font(None, 66)
        self.font_title = pygame.font.Font(None, 104)
        self.running = True

        self.saves = SaveManager(SAVE_PATH)
        data = self.saves.load()
        self.level = data["level"]
        self.score = data["score"]
        self.best_score = data["best_score"]
        self.tutorial_seen = data["tutorial_seen"]

        self.sun = Sun(CENTER, SUN_RADIUS, SUN_COLOR)
        self.meteors = MeteorSpawner()
        self.photons = PhotonField()
        self.player = Player()
        self.bg = Starfield()
        self.menu_bg = Starfield(MENU_ASTEROIDS, distant_meteors=True)

        self.state = STATE_MENU
        self.particles = []
        self.flash = 0.0
        self.death_pos = CENTER
        self.tut_dont_show = False
        self.warmup = False

        bw, bh, cx = 270, 56, WIDTH // 2
        self.menu_buttons = [
            Button((cx - bw // 2, 430, bw, bh), "EMPEZAR PARTIDA", self.start_game, accent=(255, 196, 64)),
            Button((cx - bw // 2, 500, bw, bh), "SALIR DEL JUEGO", self.quit, accent=(120, 180, 255)),
        ]
        self.gameover_buttons = [
            Button((cx - bw // 2, 430, bw, bh), "REINICIAR", self.restart, accent=(120, 230, 160)),
            Button((cx - bw // 2, 500, bw, bh), "MENU PRINCIPAL", self.goto_menu, accent=(120, 180, 255)),
        ]
        self.tut_button = Button((cx - 110, 556, 220, 54), "JUGAR", self.finish_tutorial,
                                 accent=(255, 196, 64))
        lbl_w = self.font_small.size("No volver a mostrar")[0]
        total_w = 24 + 12 + lbl_w
        self.tut_check_rect = pygame.Rect(cx - total_w // 2, 512 - 12, 24, 24)   # checkbox centrado

    # ---- persistencia ----
    def _persist(self):
        self.saves.save({"level": self.level, "score": self.score,
                         "best_score": self.best_score, "tutorial_seen": self.tutorial_seen})

    # ---- flujo de estados ----
    def reset_run(self):
        self.level = 1
        self.score = 0
        self.meteors.clear()
        self.photons.clear()
        self.particles.clear()
        self.flash = 0.0
        self.sun = Sun(CENTER, SUN_RADIUS, SUN_COLOR)
        self.player = Player()
        self.warmup = True                          # inicio facil: sin meteoritos, un solo foton
        self.photons.seed_intro(self.player.ring_index)

    def start_game(self):
        """Desde el menu: siempre empieza de cero (conserva el record)."""
        self.reset_run()
        if self.tutorial_seen:
            self.state = STATE_PLAYING
        else:
            self.tut_dont_show = False
            self.state = STATE_TUTORIAL

    def finish_tutorial(self):
        if self.tut_dont_show:
            self.tutorial_seen = True
            self._persist()
        self.state = STATE_PLAYING

    def quit(self):
        self.running = False

    # ---- acciones ----
    def _on_photon(self):
        self.score += 1
        self.best_score = max(self.best_score, self.score)
        self.player.feed_boost()
        self.particles += [Particle(self.player.pos, PHOTON_COLOR, speed=(1.0, 3.5), size=(2.0, 4.0))
                            for _ in range(10)]
        if self.warmup:                              # primer foton: arranca el juego real
            self.warmup = False
            self.photons.warmup = False
            self.meteors.timer = 50                  # breve respiro antes del primer meteorito
        if self.score % PHOTONS_PER_LEVEL == 0:
            self.level += 1
            if self.player.hp < PLAYER_MAX_HP:       # subir de nivel cura +1 vida (max 3)
                self.player.hp += 1

    def trigger_death(self):
        self.death_pos = self.player.pos
        self.meteors.remove_hits(self.player.pos, PLAYER_RADIUS)
        self.particles = [Particle(self.death_pos, random.choice(DEATH_PALETTE))
                          for _ in range(DEATH_PARTICLES)]
        self.flash = 1.0
        self.best_score = max(self.best_score, self.score)
        self._persist()
        self.state = STATE_DYING

    def restart(self):
        """Game Over -> jugar otra vez de inmediato (sin pasar por el tutorial)."""
        self.reset_run()
        self.state = STATE_PLAYING

    def goto_menu(self):
        self.reset_run()
        self.state = STATE_MENU

    # ---- ciclo ----
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if self.state in (STATE_PLAYING, STATE_DYING):
                        self.goto_menu()          # en juego: ESC vuelve al menu (ya se guardo al morir)
                    else:
                        self.running = False      # en menu/tutorial/gameover: ESC sale
                elif self.state == STATE_GAMEOVER and event.key == pygame.K_r:
                    self.restart()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if self.state == STATE_MENU:
                    for b in self.menu_buttons:
                        if b.click(event.pos):
                            break
                elif self.state == STATE_GAMEOVER:
                    for b in self.gameover_buttons:
                        if b.click(event.pos):
                            break
                elif self.state == STATE_TUTORIAL:
                    if self.tut_check_rect.collidepoint(event.pos):
                        self.tut_dont_show = not self.tut_dont_show
                    else:
                        self.tut_button.click(event.pos)

    def update(self):
        if self.state in (STATE_MENU, STATE_TUTORIAL):
            self.menu_bg.update()
        elif self.state == STATE_PLAYING:
            keys = pygame.key.get_pressed()
            self.bg.update()
            self.sun.update()
            self.player.update(keys[pygame.K_SPACE])
            if not self.warmup:                      # inicio facil: nada de meteoritos hasta el 1er foton
                self.meteors.update(self.level)
            for _ in range(self.photons.update(self.player.pos)):
                self._on_photon()
            for p in self.particles:
                p.update()
            self.particles = [p for p in self.particles if not p.dead]
            if self.player.iframes == 0 and self.meteors.hits(self.player.pos, PLAYER_RADIUS):
                self.meteors.remove_hits(self.player.pos, PLAYER_RADIUS)   # consume el meteorito que pega
                self.particles += [Particle(self.player.pos, (255, 120, 90), speed=(1.5, 5.0))
                                   for _ in range(14)]
                if self.player.hit():                                      # vulnerable tambien en el salto
                    self.trigger_death()
        elif self.state == STATE_DYING:
            self.flash = max(0.0, self.flash - 0.06)
            for p in self.particles:
                p.update()
            self.particles = [p for p in self.particles if not p.dead]
            if not self.particles:
                self.state = STATE_GAMEOVER

    def draw(self):
        self.screen.fill(BG_COLOR)
        if self.state == STATE_MENU:
            self.draw_menu()
            pygame.display.flip()
            return
        if self.state == STATE_TUTORIAL:
            self.draw_tutorial()
            pygame.display.flip()
            return

        self.bg.draw(self.screen)
        selecting = self.state == STATE_PLAYING and self.player.selecting
        draw_rings(self.screen, selecting, self.player.target_ring, self.player.ring_index)
        self.sun.draw(self.screen)
        self.photons.draw(self.screen)
        self.meteors.draw(self.screen)
        if self.state == STATE_PLAYING:
            self.player.draw(self.screen)
        if self.state in (STATE_PLAYING, STATE_DYING):
            if self.flash > 0:
                r = int(PLAYER_RADIUS + (1 - self.flash) * 100)
                add_blob(self.screen, (255, 255, 255), self.death_pos, r, int(200 * self.flash))
            for p in self.particles:
                p.draw(self.screen)
            self.draw_hud()
        else:
            self.draw_gameover()
        pygame.display.flip()

    def _blurred_menu_bg(self):
        """Fondo del menu/tutorial: estrellas+asteroides+meteoritos lejanos, desenfocado tantito."""
        tmp = pygame.Surface((WIDTH, HEIGHT))
        tmp.fill(BG_COLOR)
        self.menu_bg.draw(tmp)
        self.screen.blit(blur_surface(tmp, MENU_BLUR), (0, 0))
        dim = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        dim.fill((4, 5, 12, 120))                      # oscurece un poco para contraste
        self.screen.blit(dim, (0, 0))

    def draw_menu(self):
        self._blurred_menu_bg()
        draw_glow_text(self.screen, GAME_NAME, self.font_title, (WIDTH // 2, 250),
                       color=(250, 248, 240), glow=(255, 196, 64), spread=4)
        tag = self.font_med.render("encuentros orbitales", True, (150, 165, 200))
        self.screen.blit(tag, tag.get_rect(center=(WIDTH // 2, 318)))
        mouse = pygame.mouse.get_pos()
        for b in self.menu_buttons:
            b.draw(self.screen, self.font, b.rect.collidepoint(mouse))
        best = self.font_small.render(f"MEJOR PUNTAJE: {self.best_score}", True, (120, 135, 170))
        self.screen.blit(best, best.get_rect(center=(WIDTH // 2, 600)))

    def _tut_step(self, cx, top, draw_icon, caption):
        """Un paso del tutorial: dibujo arriba, 1-2 lineas de texto debajo."""
        draw_icon(cx, top)
        for j, ln in enumerate(caption):
            t = self.font_small.render(ln, True, (215, 224, 242))
            self.screen.blit(t, t.get_rect(center=(cx, top + 78 + j * 22)))

    def draw_tutorial(self):
        self._blurred_menu_bg()
        panel = pygame.Rect(90, 150, WIDTH - 180, 470)
        surf = pygame.Surface(panel.size, pygame.SRCALPHA)
        surf.fill((14, 18, 30, 215))
        self.screen.blit(surf, panel.topleft)
        pygame.draw.rect(self.screen, (255, 196, 64), panel, width=2, border_radius=14)

        draw_glow_text(self.screen, "COMO JUGAR", self.font_big, (WIDTH // 2, 205),
                       color=(250, 248, 240), glow=(255, 196, 64), spread=3)

        col = [WIDTH // 2 - 200, WIDTH // 2, WIDTH // 2 + 200]
        top = 300

        # Paso 1: el sol suelta un rombo -> recogelo
        def step1(cx, y):
            draw_glow(self.screen, SUN_COLOR, (cx - 38, y), 11, glow_factor=2.4)
            pygame.draw.line(self.screen, (90, 100, 130), (cx - 24, y), (cx + 18, y), 2)
            draw_diamond(self.screen, (cx + 32, y), 11, PHOTON_COLOR, filled=True, glow=True)
        self._tut_step(col[0], top, step1, ["Recoge los", "rombos"])

        # Paso 2: 5 rombos -> subes de nivel y recuperas vida
        def step2(cx, y):
            for k in range(5):
                draw_diamond(self.screen, (cx - 40 + k * 20, y), 6, PHOTON_COLOR, filled=True)
            up = self.font_med.render("Nv+", True, (180, 230, 255))
            self.screen.blit(up, up.get_rect(center=(cx, y + 26)))
        self._tut_step(col[1], top, step2, ["Junta 5: subes", "de nivel y curas"])

        # Paso 3: esquiva los meteoritos (meteorito con cola, como en movimiento)
        def step3(cx, y):
            draw_demo_meteor(self.screen, (cx + 14, y - 6), tail=(-1.0, -0.5), length=8, head_r=6)
            draw_glow(self.screen, PLAYER_COLOR, (cx - 26, y + 14), 6, glow_factor=2.6)
        self._tut_step(col[2], top, step3, ["Esquiva los", "meteoritos"])

        # checkbox "no volver a mostrar", centrado como bloque (caja + etiqueta)
        lbl = self.font_small.render("No volver a mostrar", True, (170, 182, 210))
        pygame.draw.rect(self.screen, (90, 100, 130), self.tut_check_rect, width=2, border_radius=5)
        if self.tut_dont_show:
            inner = self.tut_check_rect.inflate(-8, -8)
            pygame.draw.rect(self.screen, (255, 196, 64), inner, border_radius=3)
        self.screen.blit(lbl, (self.tut_check_rect.right + 12,
                               self.tut_check_rect.centery - lbl.get_height() // 2))

        mouse = pygame.mouse.get_pos()
        self.tut_button.draw(self.screen, self.font, self.tut_button.rect.collidepoint(mouse))

    def draw_hud(self):
        # Nivel (numero, minimo texto)
        self.screen.blit(self.font.render(f"NIVEL {self.level}", True, (180, 200, 255)), (18, 16))

        # Progreso al siguiente nivel = los rombos que has recogido (estos SON los puntos)
        got = self.score % PHOTONS_PER_LEVEL
        for i in range(PHOTONS_PER_LEVEL):
            x, y = 29 + i * 27, 60
            if i < got:
                draw_diamond(self.screen, (x, y), 9, PHOTON_COLOR, filled=True, glow=True)
            else:
                draw_diamond(self.screen, (x, y), 9, (92, 80, 46), filled=False)

        # Vidas (esquina superior derecha) = rombos coloreados como el PJ (blanco -> rojo)
        for i in range(PLAYER_MAX_HP):
            x, y = WIDTH - 30 - i * 30, 30
            if i < self.player.hp:
                draw_diamond(self.screen, (x, y), 10, self.player.hp_color(), filled=True, glow=True)
            else:
                draw_diamond(self.screen, (x, y), 10, (70, 72, 86), filled=False)

        # Mejor puntaje (con rombo), discreto abajo
        best = self.font_small.render(f"MEJOR  {self.best_score}", True, (110, 125, 160))
        self.screen.blit(best, (40, HEIGHT - 30))
        draw_diamond(self.screen, (26, HEIGHT - 22), 7, PHOTON_COLOR, filled=True)

        # Pista breve segun el momento
        if self.warmup:
            hint = "Manten ESPACIO para cambiar de anillo y alcanza el rombo"
            col = (150, 165, 205)
        else:
            hint = "ESPACIO: toque = anillo siguiente  -  manten = elegir  -  ESC menu"
            col = (95, 105, 135)
        t = self.font_small.render(hint, True, col)
        self.screen.blit(t, t.get_rect(center=(WIDTH // 2, HEIGHT - 22)))

    def draw_gameover(self):
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((4, 5, 10, 195))
        self.screen.blit(overlay, (0, 0))

        title = self.font_big.render("FIN DEL JUEGO", True, (255, 90, 70))
        self.screen.blit(title, title.get_rect(center=(WIDTH // 2, 210)))
        pts = self.font.render(f"{self.score}", True, (235, 240, 255))
        prect = pts.get_rect(center=(WIDTH // 2 + 14, 295))
        self.screen.blit(pts, prect)
        draw_diamond(self.screen, (prect.left - 22, 295), 10, PHOTON_COLOR, filled=True, glow=True)
        best = self.font.render(f"MEJOR   {self.best_score}", True, (150, 165, 200))
        self.screen.blit(best, best.get_rect(center=(WIDTH // 2, 332)))
        if self.score >= self.best_score and self.score > 0:
            rec = self.font_small.render("NUEVO RECORD", True, (255, 220, 120))
            self.screen.blit(rec, rec.get_rect(center=(WIDTH // 2, 364)))

        mouse = pygame.mouse.get_pos()
        for b in self.gameover_buttons:
            b.draw(self.screen, self.font, b.rect.collidepoint(mouse))

    def run(self):
        try:
            while self.running:
                self.handle_events()
                self.update()
                self.draw()
                self.clock.tick(FPS)
        finally:
            self._persist()
            pygame.quit()


if __name__ == "__main__":
    Game().run()