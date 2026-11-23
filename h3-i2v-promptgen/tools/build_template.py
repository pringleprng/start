"""Regenerate the TextGen instruction template from system_prompt.md.

    python h3-i2v-promptgen/tools/build_template.py

Writes user_data/instruction-templates/Inkling 2 - H3 Director.yaml: Inkling 2's
native chat format with the H3 rules as the default system message, thinking
turned off (the answer block is pre-filled) and every attached image in its own
message block, as the model expects.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT = ROOT / "user_data" / "extensions" / "h3_i2v_director" / "system_prompt.md"
OUT = ROOT / "user_data" / "instruction-templates" / "Inkling 2 - H3 Director.yaml"

TEMPLATE = """{%- set h3_system -%}
@@SYSTEM@@
{%- endset -%}
{%- set ns = namespace(has_system=false, effort=false) -%}
{%- for message in messages -%}
    {%- if message['role'] == 'system' -%}
        {%- set ns.has_system = true -%}
    {%- endif -%}
{%- endfor -%}
{%- if not ns.has_system -%}
    {{- '<|message_system|><|content_text|>' + h3_system + '<|end_message|>' -}}
{%- endif -%}
{%- for message in messages -%}
    {%- if message['role'] == 'system' -%}
        {{- '<|message_system|><|content_text|>' + message['content'] + '<|end_message|>' -}}
    {%- else -%}
        {%- if not ns.effort -%}
            {{- '<|message_system|><|content_text|>Thinking effort level: 0<|end_message|>' -}}
            {%- set ns.effort = true -%}
        {%- endif -%}
        {%- if message['role'] == 'user' -%}
            {%- set chunks = message['content'].split('<__media__>') -%}
            {%- for chunk in chunks[1:] -%}
                {{- '<|message_user|><__media__><|end_message|>' -}}
            {%- endfor -%}
            {%- set text = chunks | join('') | trim -%}
            {%- if text -%}
                {{- '<|message_user|><|content_text|>' + text + '<|end_message|>' -}}
            {%- endif -%}
        {%- elif message['role'] == 'assistant' -%}
            {{- '<|message_model|><|content_text|>' + message['content'] + '<|end_message|><|content_model_end_sampling|>' -}}
        {%- elif message['role'] == 'tool' -%}
            {{- '<|message_tool|><|content_text|>' + message['content'] + '<|end_message|>' -}}
        {%- endif -%}
    {%- endif -%}
{%- endfor -%}
{%- if add_generation_prompt -%}
    {{- '<|message_model|><|content_text|>' -}}
{%- endif -%}"""


def build() -> str:
    system = SYSTEM_PROMPT.read_text(encoding="utf-8").strip()
    if "{" in system or "}" in system:
        raise SystemExit("system_prompt.md must not contain { or } (it is embedded in a Jinja template)")
    body = TEMPLATE.replace("@@SYSTEM@@", system)
    indented = "\n".join(("  " + line) if line else "" for line in body.splitlines())
    return "instruction_template: |-\n" + indented + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(build(), encoding="utf-8")
    print(f"wrote {OUT}")
