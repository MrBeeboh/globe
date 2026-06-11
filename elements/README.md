# ELEMENTS

A falling-sand physics sandbox. One HTML file, zero dependencies, no server,
no build step. Open `index.html` in any browser and play.

## What it is

A cellular-automaton particle simulator in the lineage of the classic
"Powder Toy" games. Every pixel is a particle with its own physics, and the
fun is in how they interact:

- **fire** clings to fuel and burns through wood, plants, and oil
- **gunpowder** chain-explodes on contact with fire or lava
- **lava + water** → stone and steam; steam rises and condenses back to rain
- **acid** dissolves nearly everything except walls
- **seeds** fall, take root, and sprout plants that drink adjacent water and grow
- **ice** slowly freezes water around it; heat melts it back
- **oil** floats on water and is very easy to regret igniting

You start with a small terrain — sand dunes, a pond, a wooden cabin frame,
seeds sprouting by the water. Burn it down or build on it.

## Controls

| Action | Input |
|---|---|
| draw | left-drag |
| erase | right-drag |
| select element | click palette or keys `1–9`, `0`, `q w e r`, `x` |
| brush size | slider or `[` / `]` |
| pause / resume | `space` |
| single step | `step` button (while paused) |
| rain | toggle in the header |

## How it works

The grid is a flat `Uint8Array` (~50k–100k cells depending on window size,
3px per cell). Each frame does one bottom-up pass, alternating left/right
scan direction to avoid drift bias. Particle moves are density-based swaps,
so sand sinks through water, water sinks through oil, and gases bubble up
through everything. Rendering writes straight into an `ImageData` buffer and
blits it scaled with pixelated smoothing — no DOM, no WebGL, comfortably
60fps.
