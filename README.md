# mynixos-skills

Coding-agent skills for [MyNixOS](https://mynixos.com), packaged as a Nix
flake.

Each skill is a self-contained directory under [`skills/`](skills/) with a
`SKILL.md` (frontmatter + instructions) that an agent loads on demand. The flake
builds every skill into an installable package and exposes apps that reconcile
an agent's skill directory to exactly the set this flake declares. Skills are
built by [`agent-skill-flake`](https://github.com/nhooey/agent-skill-flake).

## Skills

| Skill                                                                  | What it does                                                                                                                                                                        |
| ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`mynixos-v1-config-change`](skills/mynixos-v1-config-change/SKILL.md) | Changes a NixOS, nix-darwin or Home Manager configuration kept on MyNixOS: test the value locally, edit it on mynixos.com with Claude in Chrome, release, build, verify and switch. |

## Install

Each skill is an output package, plus an aggregate `default` that bundles them all.

```bash
# Preview what installing every skill would change, without writing anything
nix run github:nhooey/mynixos-skills#preview

# Install all skills into the agent's skill directory
nix run github:nhooey/mynixos-skills#install

# Converge the skill directory to exactly this flake's declared set
nix run github:nhooey/mynixos-skills#reconcile

# Remove the skills this flake installed
nix run github:nhooey/mynixos-skills#uninstall
```

Package outputs:

- `agent-skills-nhooey-mynixos-all`: the aggregate of every skill (also `default`)
- `agent-skill-nhooey-mynixos-v1-config-change`

## Development

```bash
nix develop      # enter the dev shell; run `menu` to list commands
nix fmt          # nixfmt over *.nix, prettier over *.md / *.yaml
nix flake check  # runs the treefmt check (fails on any unformatted file)
```
