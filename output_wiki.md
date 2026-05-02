# StrongZombie

## TL;DR (the pitch)

A fully-playable **Plants vs Zombies clone** built in Java/JavaFX by a team of four (Illia, Mario, Mark, and Pranay) over five weeks. You click to plant sun-generating flowers and pea-shooters on a 5 × 9 grid, collect suns to buy more plants, and fend off waves of walking zombies across 7 progressively harder levels. The codebase is intentionally small and flat — every `.java` file lives in the root directory, there are no packages, and the entire game loop fits inside a single `AnimationTimer`. A clean Entity → Plant/Zombie inheritance hierarchy means adding new unit types requires only a subclass and a constructor change.

---

## Architecture (the map)

```
StrongZombie/                    ← flat root; no packages
│
├── Main.java                    ← JavaFX entry point; wires Game + MenuUI to Stage
│
├── ── MODEL ──────────────────────────────────────────────
├── Game.java                    ← God-object: entity lists, game-loop update(),
│                                   phase state machine, spawn logic, win/loss
├── Board.java                   ← 5×9 Tile grid; placePlant / removePlant / isTileOccupied
├── Tile.java                    ← Single cell; holds an optional Plant reference
│
├── Entity.java                  ← Abstract root: hp, maxHp, row/col, x/y,
│                                   takeDamage(), takeHit(), alive flag
│   ├── Plant.java               ← Abstract mid-tier: cost, cooldown, act()/draw() contract
│   │   ├── Sunflower.java       ← Produces sun every 12 s; cost 50
│   │   ├── Peashooter.java      ← Fires 1 pea/1.4 s; cost 100
│   │   ├── Repeater.java        ← Fires 2 peas/shot; cost 200
│   │   └── Walnut.java          ← High-HP blocker; cost 50
│   │
│   └── Zombie.java              ← Abstract mid-tier: move(), attack(), flash effect
│       ├── BasicZombie.java     ← Standard speed/HP
│       └── StrongZombie.java    ← 400 HP + cone sprite; added week 2
│
├── Bullet.java                  ← Projectile data + movement
├── Sun.java                     ← Collectible currency token; hover-to-collect
│
├── ── UI / RENDERING ─────────────────────────────────────
├── MenuUI.java                  ← Animated main menu; launches LevelUI or TutorialUI
├── LevelUI.java                 ← Level-select screen; calls Game.startGame()
├── TutorialUI.java              ← How-to-play screen
├── GameUI.java                  ← AnimationTimer → Game.update(); Canvas draw; mouse input
│
├── ── AUDIO ───────────────────────────────────────────────
├── SoundManager.java            ← Static singleton; loads & plays all 16 audio clips
│
└── sounds/                      ← WAV/MP3 assets (theme_menu, theme_level, peashoot,
    │                               eating, hit, gameover, level_complete, …)
    └── *.wav / *.mp3
```

**Data-flow spine:**
```
Main → MenuUI → LevelUI → GameUI
                              │
                    AnimationTimer.handle()
                              │
                         Game.update(Δt)
                         ├── Plant.act()  → Bullet list
                         ├── Zombie.act() → move / attack
                         ├── Bullet.move()
                         ├── Sun spawning / collection
                         └── Phase & win/loss check
```

---

## Onboarding Guide

### Prerequisites

| Tool | Version |
|---|---|
| JDK | 17+ |
| JavaFX SDK | 17+ (must be on the module path) |
| IDE | IntelliJ IDEA / VS Code with Java extension |

### Running the game

```bash
# 1. Clone
git clone https://github.com/illiaputintsev/plantsvszombies
cd plantsvszombies

# 2. Compile (adjust --module-path to your JavaFX lib location)
javac --module-path /path/to/javafx/lib \
      --add-modules javafx.controls,javafx.media \
      *.java

# 3. Run
java --module-path /path/to/javafx/lib \
     --add-modules javafx.controls,javafx.media \
     Main
```

> **Note:** The `sounds/` directory must be on the classpath root so `SoundManager` can resolve `/sounds/*.wav`. If you run from an IDE, mark the project root as a resources folder.

### Mental model in 5 minutes

1. **`Main.java`** is three lines of real work: call `SoundManager.init()`, create `new Game()`, hand both to `new MenuUI(stage, game)`, call `ui.show()`. Everything else flows from those three objects.

2. **`Game`** is the single source of truth. It holds `List<Plant>`, `List<Zombie>`, `List<Bullet>`, `List<Sun>`, the sun balance, the current level, and the phase counter. Nothing mutates game state except `Game` itself (or entities via references `Game` passes them).

3. **`GameUI`** owns the `AnimationTimer`. Every ~16 ms it calls `game.update(deltaTime)`, then redraws the `Canvas`. Mouse clicks are translated to grid coordinates and forwarded to `game.tryPlant(row, col)` or `game.tryRemovePlant(row, col)`.

4. **Entities know how to draw themselves.** Each `Plant` and `Zombie` subclass holds a `draw(GraphicsContext gc)` method. `GameUI` iterates all live entities and calls `draw()` — it has no plant- or zombie-specific rendering code.

5. **The shop** is a static array in `GameUI` (`SHOP_NAMES`, `SHOP_COSTS`). The selected index is stored on `Game` as `selectedPlant`. Clicking a grid cell while a plant is selected calls `Game.tryPlant()`, which checks `Board.isTileOccupied()` and the sun balance before placing.

### Your first change: add a new plant

1. Create `MyPlant.java` — `extends Plant`.
2. Implement `act(List<Entity>, List<Bullet>, Game, double)` — shoot, heal, produce suns, whatever.
3. Implement `draw(GraphicsContext)` — use the `gc` primitives; copy `Peashooter.draw()` as a template.
4. In `GameUI.java`, add your plant's name to `SHOP_NAMES` and its cost to `SHOP_COSTS`.
5. In `Game.java`, find `tryPlant()` — add a `case` for your new shop index that calls `new MyPlant(row, col)`.
6. Done. Run the game; your plant appears in the shop.

### Your first change: add a new zombie

1. Create `MyZombie.java` — `extends Zombie`.
2. Call `super(HP, row, col, speed)` in the constructor.
3. Override `act(List<Plant>, List<Zombie>, double)` — almost always just `move()` then `attack()`.
4. Override `draw(GraphicsContext)` — call `super.draw(gc)` first to get the base body + HP bar, then draw your distinguishing feature on top (see `StrongZombie.draw()` for a minimal example).
5. In `Game.java`, add your zombie to the spawn logic inside `spawnZombie()`.

### Key files to read in order

| Order | File | What you learn |
|---|---|---|
| 1 | `Main.java` | Bootstrap wiring |
| 2 | `Entity.java` | Root type; damage model |
| 3 | `Plant.java` | `act()` / `draw()` contract |
| 4 | `Sunflower.java` | Simplest concrete plant |
| 5 | `Zombie.java` | Movement, blocking, flash |
| 6 | `StrongZombie.java` | Minimal subclass example |
| 7 | `Game.java` | Full game-loop brain |
| 8 | `GameUI.java` | Rendering + input wiring |

---

## The Story

### Phase 1 — Foundations (mid-March 2026)

The project started with the expected scaffolding: `Entity`, `Plant`, `Zombie`, `Board`, and `Tile` were stood up in the first week. One notable early stumble: `Entity` briefly had `extends Game` — a circular dependency introduced during fast parallel development and patched the same day. It was an early signal that four people working in the same flat namespace would generate friction. The `maxHp` field was also added retroactively around 24 March once health bars were needed, confirming the base class was being designed as the team went.

### Phase 2 — Core Gameplay (late March)

The bulk of game logic — sun economy, the phase state machine inside `Game.update()`, wave spawning, and collision/bullet resolution — was written in one late-night mega-commit. All the magic numbers for balance (spawn intervals, wave zombie counts, sun drop rate, phase transition thresholds) were inlined at this point and never decomposed into named constants. The comment `SUN_DROP_INTERVAL = 15.0` is as close to documentation as these numbers get.

### Phase 3 — StrongZombie and the proof of good design (week 2)

A single commit titled *"Add levels, improve UI, add StrongZombie, add levels"* (the duplicated "add levels" hinting at a rushed message) brought in the cone-headed zombie. The implementation is clean: `StrongZombie` is 45 lines, overrides only `draw()` to paint an orange cone on top of the shared body, and passes `400` HP and a slightly reduced speed into `super()`. No behaviour was duplicated. The `Zombie` base class paid its design debt.

### Phase 4 — Audio bolted on

`SoundManager` arrived as a late addition. Volume was adjusted at least three separate times in the git log. The `theme_level.wav` music was separately wired to stop when a level ended. Sound effects were originally firing inside `draw()` calls — meaning every frame (~60×/second) instead of once per event. This ran broken for roughly a week. Mark's `13:24` commit on the final day, *"Sounds moved from rendering to logic blocks"*, fixed it.

### The Final Day (2026-04-03) — 16+ commits in ~12 hours

The entire polish layer landed under deadline pressure:

| Time | Author | Commit |
|---|---|---|
| 02:57 | Mark | `Tutorial added + slight redesign` |
| 03:15 | Mark | `Sun collecting sound` |
| 10:36–11:02 | Mario | `Adding pause feature` → `Added pause logic and button to gameUI` |
| 11:10 | Illia | `animated menu + house redesign` |
| 12:04 | Mario | `Balanced zombies` |
| 12:41 | Mark | `Fixed Inheritance issues` |
| 13:00 | Mario | `Changed naming convention` |
| 13:24 | Mark | **`Sounds moved from rendering to logic blocks`** ← critical fix |
| 13:43 | Mario | `Accept remote GameUI.java` ← hottest merge conflict |
| 14:23 | Illia | `Add zombies stack logic` |
| 14:37 | Mark | `Add null check` ← audio crash patch |
| 14:57–15:05 | Mario / Illia | Final Javadoc pass, PR merge |

A cosmetic bug — the in-game currency displaying as "dollars" instead of "suns" — survived the entire development cycle and was fixed at `00:52` on that same final day. Classic sign of a team eyes-down on functionality.

### Scar Tissue Summary

| File | Wound |
|---|---|
| `Entity.java` | `extends Game` circular dep (patched day-of); `maxHp` added retroactively |
| `Game.java` | All balance constants are inline literals; phase machine is an implicit `int`; never decomposed |
| `GameUI.java` | Sound-in-draw bug lived for ~1 week; most-contested file (multiple merge conflicts) |
| `SoundManager.java` | Volume changed 3× across project; null-check added hours before submission |
| `StrongZombie.java` | Rushed commit message; but the code itself is clean — testament to the `Zombie` base class |

---

## Deep Dive

### The Entity Hierarchy — One Contract, Many Actors

```
Entity          (hp, maxHp, row, col, x, y, alive, takeDamage, takeHit)
├── Plant       (cost, cooldown, timer, act(), draw())
│   ├── Sunflower   — economy; produces 25 sun every 12 s
│   ├── Peashooter  — offense; 1 pea/1.4 s when zombie in row
│   ├── Repeater    — offense; 2 peas/shot; cost 200
│   └── Walnut      — defense; high HP tank, no attack
└── Zombie      (speed, eating, eatTimer, attackInterval, flashTimer, move(), attack())
    ├── BasicZombie  — standard stats
    └── StrongZombie — 400 HP, slower (speed 22), cone hat
```

Every `Plant` implements `act(List<Entity>, List<Bullet>, Game, double)`. The `List<Entity>` parameter gives targeting plants (Peashooter, Repeater) access to live zombies without coupling to `Game`. `SoundManager` calls inside `act()` — never inside `draw()`.

Every `Zombie` implements `act(List<Plant>, List<Zombie>, double)`. The pattern is invariably:
```java
boolean moved = move(deltaTime, plants, allZombies);
if (!moved) attack(deltaTime, plants);
```
The `Zombie` base class handles spacing (minimum 20 px gap between zombies in the same row) and the damage-flash white overlay — both features work for free on any subclass.

---

### Game.java — The God Object and Its Magic Numbers

`Game` is a **God Object by necessity, not ignorance**: for a five-week academic project with four parallel contributors, centralising all state in one class prevented merge conflicts more than it created them. Costs and cautions:

- **All wave/balance constants are inline literals** inside `update()` and the spawn methods. `spawnInterval`, wave zombie counts, sun drop rate (`SUN_DROP_INTERVAL = 15.0`), and phase transition thresholds are never named or documented elsewhere. A *"Balanced zombies"* commit landed on the **final day**, meaning these numbers were empirically tuned under deadline. Treat them as load-bearing; document before changing.

- **The phase state machine** is an `int phase` plus a `double phaseTimer`. There is no `Phase` enum or transition table — you must read `update()` sequentially to understand the flow. Inserting a new phase requires updating **all** branching conditions on `phase` throughout the method.

- **Grid constants** (`ROWS`, `COLS`, `CELL_W`, `CELL_H`, `GRID_X`, `GRID_Y`) are `public static final` on `Game` and referenced directly from rendering code. Changing grid size is a multi-file operation.

- **Level configuration** lives in a series of `if (level == N)` blocks inside `Game`. Copy the pattern of an existing level block when adding a new one.

---

### GameUI — Sound Belongs in Logic, Not Rendering

The most-contested file in the repo. The critical historical lesson: **sound effects were originally fired inside `draw()` calls**, triggering ~60 times per second instead of once per event. This ran broken for roughly a week. The fix — moving audio calls into game-logic blocks — landed at `13:24` on the final day.

**Consequence for future work:** if you refactor rendering, audit every `SoundManager` call. The architecture is now correct (sound in logic, not draw), but the pattern is fragile because `GameUI` still mixes three responsibilities in one class:

| Responsibility | Where it lives now | Ideal future home |
|---|---|---|
| Canvas drawing | `GameUI` | `GameRenderer` |
| Mouse input | `GameUI` | `GameInputHandler` |
| Game loop timing | `GameUI` (AnimationTimer) | `GameLoop` |

That refactor is safe but non-trivial due to shared local variables.

---

### SoundManager — Bolted On, Barely Stable

`SoundManager` was added in Phase 4. Volume was adjusted at least three times. A null-check was added hours before submission — implying a `NullPointerException` was observed in testing very close to the deadline. The check is a band-aid; the root cause (a media asset that may not load in all environments) was never resolved.

**Rules when touching audio:**
1. Always null-check before calling any `SoundManager` method.
2. Wrap new asset loading in a try-catch (the private `loadSound()` helper already does this — use it).
3. Never call `SoundManager` from inside a `draw()` method.

---

### The `Zombie` Base Class — The Architectural Success Story

Lane movement, plant-blocking, zombie-spacing, eating/attack behaviour, and the hit-flash visual effect are all implemented **once** in `Zombie`. `StrongZombie` was added a week in as a single ~45-line commit and required only a constructor change (higher HP, slower speed, different hat drawn with `gc.fillPolygon`). Zero behaviour duplication. Any new zombie type should follow exactly the same pattern.

---

### Extension Points (Safe to Touch)

| What to extend | How |
|---|---|
| New plant type | Subclass `Plant`, implement `act()` + `draw()`, register in `GameUI.SHOP_NAMES/COSTS` and `Game.tryPlant()` |
| New zombie type | Subclass `Zombie`, override only what differs (HP, speed, sprite) in constructor + `draw()` |
| New level | Add an `if (level == N)` configuration block in `Game`'s level-init logic; copy an existing block |
| New screen | Create a UI class accepting `(Stage, Game)`, follow the `MenuUI` → `LevelUI` → `GameUI` handoff pattern |

---

### Known Fragility Hotspots

| Area | Risk |
|---|---|
| `Game.update()` magic numbers | Silent balance breakage if changed without playtesting all 7 levels |
| `SoundManager` null safety | Potential crash if audio assets are missing or slow to load |
| Final-day polish code | Pause, animated menu, tutorial — added in 16+ commits in one day; lightly tested |
| Flat file structure | No packages; any class name collision is a compile error; consider namespacing before the file count grows |
| `phase` integer state machine | No enum; adding a phase requires reading all of `update()` carefully |

---

## Where to Look For Things

| Concern | File(s) |
|---|---|
| App bootstrap & Stage wiring | `Main.java` |
| Game loop (tick / delta time) | `GameUI.java` — `AnimationTimer` inside `launch()` |
| All game state (entities, sun, score, level) | `Game.java` |
| Phase / wave progression logic | `Game.java` → `update()` |
| Wave balance & spawn timing constants | `Game.java` — inline literals in `update()` / spawn methods |
| Win / loss detection | `Game.java` → `update()` |
| Grid layout constants (ROWS, COLS, CELL sizes) | `Game.java` — `public static final` fields |
| Tile occupancy / plant placement rules | `Board.java`, `Tile.java` |
| Shared entity contract (HP, damage, alive) | `Entity.java` |
| All plant behaviour contracts | `Plant.java` |
| Sun production | `Sunflower.java` |
| Single-pea shooting | `Peashooter.java` |
| Double-pea shooting | `Repeater.java` |
| High-HP blocking | `Walnut.java` |
| All zombie behaviour contracts | `Zombie.java` |
| Standard zombie | `BasicZombie.java` |
| High-HP cone zombie | `StrongZombie.java` |
| Projectile movement | `Bullet.java` |
| Collectible sun tokens | `Sun.java` |
| Canvas rendering & mouse input | `GameUI.java` |
| Main menu (animated) | `MenuUI.java` |
| Level select screen | `LevelUI.java` |
| Tutorial screen | `TutorialUI.java` |
| All audio playback | `SoundManager.java` |
| Audio asset files | `sounds/*.wav`, `sounds/*.mp3` |