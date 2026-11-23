# H3 I2V Director: MiniMax H3 prompts from plain language, inside TextGen

Describe what should happen in your own words and add the picture. Inkling 2 Mini (uncensored) looks at
the picture and writes a complete **MiniMax H3 (Hailuo 3) image-to-video prompt** in MiniMax's official
format. The tab then checks and repairs the format, so the result is ready to paste.

![The H3 I2V Director tab in TextGen](docs/tab.png)

- **Runs locally in [TextGen](https://github.com/oobabooga/textgen)** (oobabooga's text-generation-webui).
- **Vision model included:** Inkling 2 Mini reads images itself. With its `mmproj` file loaded it is
  both the prompt writer and the "eyes".
- **Official H3 format** from MiniMax's own prompt-writing guide
  ([MiniMax-AI/MiniMax-H3 → `skills/h3-prompt-writing`](https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills/h3-prompt-writing)),
  the format their own prompt rewriter (H3-Context-IR) produces.
- **Modes:** I2VA (picture = first frame), FL2VA (first + last frame), L2VA (picture = last frame),
  T2VA (text only).
- **Made for Bazzite + RTX 5080 (16 GB VRAM) with 16 GB RAM:** a one-file setup script that picks a model
  size your memory can hold, and a VRAM budget, so Inkling fits on the GPU next to Fooocus.

## Bazzite + RTX 5080: install with one script

Needs Bazzite's **NVIDIA image** (the `-nvidia-open` variant, which RTX 50-series cards require), driver 570
or newer (`nvidia-smi` shows it) and about **20 GB of free disk**. 16 GB of RAM works (see
[Fitting on the GPU next to Fooocus](#fitting-on-the-gpu-next-to-fooocus)).
Nothing is installed system-wide; everything goes into `~/AI/textgen`.

Download the one script and run it (in a normal terminal, as your normal user, no `sudo`):

```bash
curl -fLo ~/h3-director-setup.sh https://raw.githubusercontent.com/pringleprng/start/ccr-df6920e9-t3vfcw/h3-i2v-promptgen/h3-director-setup.sh
bash ~/h3-director-setup.sh
```

`h3-director-setup.sh` is everything in one file: the installer plus the H3 tab, its rules, the Chat
template and the preset, built in. Options go after it, for example `bash ~/h3-director-setup.sh --vram-budget 7`
(`--help` lists them all). Or without saving the file first:
`curl -fsSL https://raw.githubusercontent.com/pringleprng/start/ccr-df6920e9-t3vfcw/h3-i2v-promptgen/h3-director-setup.sh | bash`

The script:

1. checks the GPU and driver with `nvidia-smi`;
2. installs **TextGen** portable (CUDA build, its own Python) into `~/AI/textgen/textgen-<version>/`;
3. installs **llama.cpp** (newest release, b12638 or later, needed for Inkling 2) as the CUDA 12.8 build, which
   has native RTX 50-series kernels. It puts NVIDIA's CUDA runtime (`libcudart`, `libcublas`) next to it,
   because Bazzite has no CUDA toolkit; only the NVIDIA driver is needed. It then checks that llama.cpp
   sees the card (`CUDA0: NVIDIA GeForce RTX 5080`);
4. downloads **Inkling 2 Mini Uncensored** and its **mmproj** (vision) from Hugging Face. The size is
   chosen from your RAM: the biggest file up to *RAM − 5 GB* (about **10–11 GB with 16 GB RAM**, a
   ~3-bit quant such as IQ3_XXS; with 32 GB+ it takes Q4_K_M). It checks several uncensored uploads if the
   first has no suitable size (`--quant Q4_K_M` or `--repo` to choose yourself);
5. adds the H3 tab, turns it on in `CMD_FLAGS.txt`, and sets Inkling to load automatically within a
   **6.5 GB VRAM budget**, so it fits next to Fooocus (`--vram-budget 7` to change it, `--profile full` for
   the whole GPU);
6. creates **TextGen H3 Director** in the app menu and `~/AI/textgen/start-h3-director.sh`.

`user_data` (models, settings, prompts) sits next to the TextGen folders, so TextGen updates keep it.
Run the script again any time to update; finished downloads are skipped, interrupted ones resume.

Start **TextGen H3 Director**. Inkling loads by itself (watch the status line at the top of the
**H3 I2V Director** tab), then you're ready.
`start-h3-director.sh --browser` runs without the desktop window (open http://127.0.0.1:7860);
`--listen` makes it reachable from other devices on your network.

### Fitting on the GPU next to Fooocus

Your memory: **16 GB VRAM** (RTX 5080) + **16 GB RAM**, shared with Bazzite, Fooocus and TextGen.
Fooocus (SDXL) needs roughly 8 GB of the VRAM while it generates. The setup is made for that:

- **Model size:** the installer takes a ~10–11 GB Inkling file instead of the 16 GB Q4_K_M, which would not
  fit in 16 GB of RAM next to Fooocus. Inkling is a mixture-of-experts model (26 B parameters, about 3.4 B
  active per token), so it stays usable at ~3 bits. It is somewhat less precise than Q4_K_M, and the
  format check repairs most structural slips. With 32 GB RAM later, run `h3-director-setup.sh` again with
  `--quant Q4_K_M`.
- **VRAM budget:** with the default *Fit next to Fooocus* profile, Inkling (model + vision file + context)
  uses at most the budget (default **6.5 GB**). When you press *Load Inkling* (or at start-up), the tab
  measures the GPU's free memory and tells llama.cpp how much to leave free. The budget therefore holds
  whether Fooocus is already running or starts later. llama.cpp keeps the attention layers on the GPU and
  moves MoE expert weights to system RAM first. About 5 GB of the model sits in VRAM and the remaining
  ~5 GB in RAM.
- **Context:** 12k tokens instead of 16k. The rules, a picture, the answer and a repair pass need about 9k.

| GPU profile | What it does |
|---|---|
| **Fit next to Fooocus** (default) | Inkling stays within the VRAM budget (slider in the panel); the rest of the model goes to system RAM. |
| **Whole GPU** | Fits as much of Inkling into VRAM as possible (1 GB left free). The ~10 GB file fits entirely, so this is the fastest. Use it when Fooocus is closed. |

- The status line shows the GPU's memory in use and **how much of it Inkling takes**.
- **Load Inkling** / **Unload (free the GPU)** switch profiles or budgets in seconds without restarting TextGen.
- If Fooocus runs out of memory, lower the budget (5–6 GB) and press *Load Inkling* again. If Fooocus is
  closed most of the time, raise it or use *Whole GPU*: more VRAM = faster.
- RAM is the tight part. Bazzite's compressed swap (zram) catches short peaks. If the system starts to
  stutter while both run, close other big programs (browsers with many tabs, games), or install a smaller
  file: `bash ~/h3-director-setup.sh --quant IQ2_M`.

## What's in this folder

| Path | What it is |
|---|---|
| `h3-director-setup.sh` | **The one-file setup**: installer + all H3 files built in (generated, don't edit) |
| `bazzite/install.py` | The installer's source (also runs on its own from a clone) |
| `tools/build_setup_script.py` | Rebuilds `h3-director-setup.sh` after changing the installer or any H3 file |
| `user_data/extensions/h3_i2v_director/` | The **H3 I2V Director** tab (TextGen extension) |
| `user_data/extensions/h3_i2v_director/system_prompt.md` | The H3 rules the model follows (edit to taste) |
| `user_data/instruction-templates/Inkling 2 - H3 Director.yaml` | Same rules for TextGen's normal **Chat** tab |
| `user_data/presets/H3 Director.yaml` | Sampling preset (temperature 0.8, top_p 0.95, min_p 0.05) |
| `tools/build_template.py` | Rebuilds the Chat template after you edit `system_prompt.md` |
| `tests/` | Tests (`python -m unittest discover -s h3-i2v-promptgen/tests`), incl. a check that the setup script is up to date |

## Manual setup (Windows, other Linux, Mac)

You need a PC (Windows, Linux or Mac), not a phone. Inkling 2 Mini has 26 B parameters but only about
3.4 B are active per token, so it runs on a CPU, faster with a GPU. A Q4_K_M file (~16 GB) wants **32 GB of
RAM** (or RAM + VRAM); with 16 GB RAM pick a ~10 GB file (IQ3_XXS / Q2_K) instead.

### 1. Install TextGen

Download the portable build for your system from
[github.com/oobabooga/textgen/releases](https://github.com/oobabooga/textgen/releases), unzip it and start
it (`textgen`, or `start_windows.bat` / `start_linux.sh` / `start_macos.sh` in the full version).
It opens at http://127.0.0.1:7860.

### 2. Add a newer llama.cpp (needed for Inkling 2)

Inkling 2 support was added to llama.cpp on 15–21 November 2026. The llama.cpp built into TextGen (v4.9)
is from June 2026 and cannot load the model yet ("unknown model architecture: inkling2").
Once TextGen ships a newer llama.cpp you can skip this step.

1. Open [github.com/ggml-org/llama.cpp/releases](https://github.com/ggml-org/llama.cpp/releases) and take
   release **b12638 or newer** (22 Nov 2026+).
2. Download the file for your machine:
   - Windows + NVIDIA: `llama-bXXXXX-bin-win-cuda-12.4-x64.zip` and `cudart-llama-bin-win-cuda-12.4-x64.zip`.
     If the CUDA zip only contains `ggml-cuda.dll`, also download `llama-bXXXXX-bin-win-cpu-x64.zip`.
   - Windows, other GPU: `...-bin-win-vulkan-x64.zip` (or `...-bin-win-cpu-x64.zip` for CPU only)
   - Linux + NVIDIA: `...-bin-ubuntu-cuda-12.8-x64.tar.gz` and `cudart-llama-bXXXXX-bin-ubuntu-cuda-12.8-x64.tar.gz`
     (the CUDA runtime; needed unless you have the CUDA toolkit installed). Other: `...-bin-ubuntu-vulkan-x64.tar.gz`
     or `...-bin-ubuntu-x64.tar.gz`. On Bazzite, use [the setup script](#bazzite--rtx-5080-install-with-one-script) instead.
   - Mac (Apple Silicon): `...-bin-macos-arm64.tar.gz`
3. Unpack it into `user_data/llama-cpp/` inside TextGen (it creates a folder like `llama-b12638/`). Put the
   files from the `cudart-…` download **into that same folder, next to `llama-server`**.

The H3 tab finds `llama-server` there by itself and makes TextGen's llama.cpp loader use it. You don't
replace any TextGen files. Delete the folder to go back. (A file or folder path can also be set under
*Model and backend settings*, or in the `H3_LLAMA_SERVER` environment variable.)

### 3. Download Inkling 2 Mini Uncensored + its vision file

From one uncensored GGUF repository on Hugging Face (for example
[Abiray/Inkling-2-Mini-Uncensored-GGUF](https://huggingface.co/Abiray/Inkling-2-Mini-Uncensored-GGUF);
others: KookiesXy, ghost-actual, AtomicChat, all `…/Inkling-2-Mini-Uncensored-GGUF`) download:

- the model: the file ending in **`Q4_K_M.gguf`** (Q5_K_M / Q6_K / Q8_0 if you have the memory)
  → put it in `user_data/models/`
- the vision projector: the file starting with **`mmproj-`** (for example `mmproj-Inkling-2-Mini-Uncensored-BF16.gguf`)
  → put it in `user_data/mmproj/`

Take both files from the **same** repository.

### 4. Install the H3 tab

Copy the contents of this folder's `user_data/` into TextGen's `user_data/` (it only adds new files:
`extensions/h3_i2v_director`, an instruction template and a preset).

Turn the tab on: **Session** tab → tick `h3_i2v_director` → *Apply flags/extensions and restart*.
Or add this line to `user_data/CMD_FLAGS.txt`:

```
--extensions h3_i2v_director
```

Don't put `--model` in `CMD_FLAGS.txt`. A model given there is loaded before the tab can point TextGen at
the newer llama-server.

### 5. Load the model

In the **H3 I2V Director** tab, open **Model and GPU**. The Inkling GGUF and its mmproj are picked
automatically. Choose a GPU profile (see [Fitting on the GPU next to Fooocus](#fitting-on-the-gpu-next-to-fooocus))
and press **Load Inkling**. Tick *Load automatically when TextGen starts* and press *Save settings* to skip
this next time.

(The normal Model tab works too: Model = the Inkling GGUF, Multimodal (vision) = the `mmproj-…` file,
ctx-size 16384, Load.)

The status line at the top should now show `vision on · Inkling native format`.

## Using it

1. **Mode**: leave on *I2VA* for image-to-video.
2. **Picture 1**: drop in the image you will give MiniMax H3 as the first frame (or paste it).
3. **Your idea**: what should happen, in plain words, any language. For example *"she looks up, smiles at the rain,
   then splashes through a puddle"*.
4. **Duration**: the length you will generate on H3 (4–15 s). Cut times are kept inside it.
5. Optional: shots, camera move (+ amplitude / speed), spoken lines (kept word for word), music or
   complete silence, a style.
6. Optional: **👁 Describe picture** shows what the model reads from the image. Correct anything wrong;
   the notes are sent with the request.
7. **Generate H3 prompt** → copy it with the button in the corner of the output box. Use it on H3 with the
   **same picture** and **the same duration**.

Under the output you get two checks:

- **Format check**: the official H3 rules. Exact first line, the three fields in order, `[Shot 1]` opening
  with style and composition, later shots with increasing cut times inside the duration and a cut phrase
  ("the camera cuts to …"), camera motion as a sentence (no `[Pan left]`), dialogue as
  `(S1) says: <d>[Language] …</d>`, the exact voiceover wording, picture labels only for attached
  pictures, 1–4 sentences of soundscape, and 1–3 sentences of music without mood words.
  ❌ = error, ⚠️ = note, 🔧 = fixed automatically.
- **Matches your request**: the shot count, camera move, amplitude and speed you chose; your lines word for
  word with the right language tag; no invented dialogue; silence / no music when asked; your style; the
  **people and actions of your idea** (see below); and how many key words of your idea the description
  contains (synonyms are fine, so that one is only a hint).

**People are kept exactly, in your words.** The tab reads the people and actions from your idea and spells
them out for the model. For *"a woman standing next to a girl, the woman hands the girl a cup"* it asks for:
exactly one woman and one girl, called "the woman" and "the girl" every time, each on her own side of the frame
(left / right), no ages added, and the woman hands while the girl receives. The check then flags:
- another word for one of them ("the child", "the lady", "young woman", "two women");
- added ages ("of about seven", "in her forties", "an adult");
- a missing or extra person;
- an action the wrong way round (the girl handing the cup to the woman);
- a "She …" sentence when two females are in the scene and it could mean either;
- two people of the same kind not told apart.

Two women are told apart by your own words ("the older woman" / "the younger woman") or by clothing or
position ("the woman in the red coat"), the way MiniMax's own example prompts label each person. This check
works for English ideas (woman, man, girl, boy, child, baby, teenager, mother, father, daughter, son,
grandmother, …); ideas in other languages still get the rules, without the extra check.

**🧪 Self-test** (accordion under the buttons) runs eight basic plain-language ideas through your loaded
model, exactly like *Generate*, and shows a pass/fail table. They cover a simple idea, a static camera with no
music, two shots with a spoken line, complete silence, a woman handing a girl a cup, two women told apart, and
with a picture in *Picture 1* also push in and a Spanish line. Run it once after installing to see how well Inkling follows the H3 rules on your machine.

**Thinking**: *off* is fastest and fine for most ideas. *low* or *medium* lets Inkling plan first, which helps
complex multi-shot ideas, at the cost of time.

### What you get

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium shot frames the young woman shown in <Picture 1> standing on a rainy city sidewalk at night, preserving her yellow raincoat, short black hair, the red umbrella in her left hand and the glowing shop windows behind her. She tilts the umbrella back, looks up at the rain and breaks into a wide smile as drops land on her face. The camera pushes in with small amplitude at slow speed. The young woman with a bright, clear voice (S1) says: <d>[English] Finally, rain!</d> [Shot 2] At 00:05.500, the camera cuts to a low close-up of her yellow boots splashing through a puddle as neon reflections ripple outward across the wet pavement.

overall_soundscape: Steady rain hisses on the pavement and drums on the umbrella. Boots splash through the puddle.

non_diegetic_music: A light, plucked ukulele melody at a moderate tempo with soft hand claps.
```

The rules the model follows (full text in `system_prompt.md`): MiniMax's official H3 guide, plus what
MiniMax's own H3 video skills and H3 users add:

- Line 1 is MiniMax's fixed instruction for the mode, exact to the character. FL2VA and L2VA lines carry the
  last shot number and the duration (`8.00`). T2VA has no instruction line.
- Then three fields, in this order: `integrated_multimodal_description` (the timeline: what you see and hear),
  `overall_soundscape` (ambience and action sounds, 1–4 sentences), `non_diegetic_music` (score only the
  audience hears, 1–3 sentences, or `N/A`).
- I2VA: anchor on what the picture shows (people, clothes, colors, layout stay the same), then action onset,
  development, result.
- `[Shot 1]` has no time. Later shots start `[Shot 2] At 00:04.500, the camera cuts to …` with increasing
  times inside the duration.
- Camera motion as a sentence: type (push in, pull out, pan, truck, tilt, pedestal, zoom, arc, tracking,
  static, shake, POV, roll) + optional `with small/large amplitude` + `at slow/fast speed`. No Hailuo 2.x
  bracket commands like `[Pan left]`.
- Speakers get IDs and a voice: `The young woman with a quiet voice (S1) says: <d>[English] …</d>`. Your
  lines are never translated or changed. Voiceover: `says in an off-screen voiceover: … while his lips remain
  completely closed`.
- Visible text in double quotes, verbatim. No subtitles, captions, logos or text you didn't ask for: H3 draws
  whatever text is described. Plain sentences only, no arrows, slashes, "+" or markdown (H3 can draw them too).
- People in your words, each on a fixed side of the frame, with the same wording every time. Only the speaker's
  mouth moves during a line.
- The whole clip is filled (no empty opening, time words for the beats, a stated end state). Each new shot
  continues from the previous one, keeping positions and one light direction.
- Concrete details, no hype words ("masterpiece", "8K", …). If something must *not* happen, one short
  "No …" sentence (H3 has no separate negative prompt). The whole prompt stays under 7,000 characters,
  H3's limit.

The checker in `h3_core.py` enforces the structure. MiniMax's own published T2VA and I2VA example prompts pass
it unchanged.

> This is the format the H3 model itself reads. MiniMax's site and API may still run their own rewriter
> over whatever you paste. A prompt already in this format leaves it nothing to guess. If you use the API with
> **H3-Max**, a third-party guide reports a `prompt_expansion_mode` setting; `disabled` would send the prompt
> as it is (not confirmed by MiniMax's docs). With a picture, the video takes the picture's aspect ratio.

## Using the normal Chat tab instead

**Parameters** tab → *Instruction template* sub-tab → *Saved instruction templates* →
**Inkling 2 - H3 Director** → **Load**; *Preset* → **H3 Director**. In the **Chat** tab set *Mode* to
**instruct**, attach the picture with 📎 and type your idea, including the length ("8 seconds"). The template contains the H3 rules, turns thinking off and puts the picture where
Inkling expects it. The tab is still better: it adds the fixed first line, checks the format and repairs it.

## Plan B: run llama-server yourself

If TextGen won't load the model, run the newer llama-server directly and point the tab at it:

```bash
llama-server -m Inkling-2-Mini-Uncensored-Q4_K_M.gguf --mmproj mmproj-Inkling-2-Mini-Uncensored-BF16.gguf -c 16384 --jinja --port 8080
```

(add `-ngl 99` to put the model on an NVIDIA GPU). In the H3 tab: *Model and backend settings* → Backend
**OpenAI-compatible server (URL)** → `http://127.0.0.1:8080/v1` → *Save settings*. The same works for
LM Studio, Ollama or any OpenAI-compatible server with a vision model.

## Troubleshooting

| Message | Fix |
|---|---|
| `unknown model architecture: 'inkling2'` when loading | Step 2: newer llama.cpp in `user_data/llama-cpp/`, restart TextGen, load with *Load Inkling* (not `--model`) |
| *The loaded model can't see pictures* | Pick the `mmproj-…` file in *Model and GPU* and press *Load Inkling* again |
| *The request needs about N tokens, but the model was loaded with a context of …* | Load the model with ctx-size 16384 or more |
| *No model is loaded* | *Model and GPU* → *Load Inkling* (or switch the backend to a server URL) |
| Installer: *llama.cpp does not see the GPU* (Bazzite) | You are on a non-NVIDIA Bazzite image or the driver isn't running: check `nvidia-smi`; RTX 50 cards need the `-nvidia-open` image |
| Fooocus runs out of GPU memory | *Model and GPU* → lower the VRAM budget (e.g. 5) → *Load Inkling* (or *Unload* while Fooocus works) |
| The PC stutters / swaps with both running | 16 GB RAM is tight: close other big programs, or run `bash ~/h3-director-setup.sh --quant IQ2_M` |
| *Could not reach http://…/chat/completions* | Start llama-server, check the URL and port |
| ⚠️ *Finished, but the format check still finds problems* | Generate again, set Thinking to *low*, or fix by hand and press *Re-check* |
| The tab is missing | Session tab → tick `h3_i2v_director` → apply and restart |

## Customizing

- Change the rules in `user_data/extensions/h3_i2v_director/system_prompt.md` (keep it free of `{` and `}`),
  restart TextGen, then run `python tools/build_template.py` and copy the new template so the Chat tab matches.
- Settings saved with *Save settings* go to `user_data/extensions/h3_i2v_director/settings.json`.
- After changing the installer or any file under `user_data/`, run `python tools/build_setup_script.py` so
  `h3-director-setup.sh` carries the new version (the tests fail until you do).
