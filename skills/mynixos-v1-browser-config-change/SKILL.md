---
name: mynixos-v1-browser-config-change
description: Change a NixOS, nix-darwin or Home Manager configuration that lives on MyNixOS (mynixos.com, the v1 website) by editing it in the browser with Claude in Chrome, then release it, build it locally, verify the build and switch to it. Use it whenever a configuration managed on MyNixOS needs a change (packages, Homebrew, services, shell, dotfiles, any option), and whenever MyNixOS settings, outputs, inputs, releases or a switch come up.
---

# Change a configuration on MyNixOS v1 through the browser

This skill drives the v1 website at mynixos.com in a browser, not an API.
MyNixOS keeps the configuration as settings on its website, not as files in a
local repository. A change goes through five steps, in order:

1. Test the new value locally.
2. Edit the setting on mynixos.com in the browser.
3. Publish a release.
4. Build the release locally and check the result.
5. Switch, then check the change on the running system.

In the commands below, replace:

- `<owner>/<flake>` with the flake's path on MyNixOS, as in
  `https://mynixos.com/<owner>/<flake>`
- `<host>` with the system output's name, as in
  `darwinConfigurations.<host>` or `nixosConfigurations.<host>`
- `<target>` with the configuration a setting applies to (a host, or a Home
  Manager user)

## How MyNixOS is laid out

- **Outputs** (`https://mynixos.com/<owner>/<flake>/outputs`): the flake's
  outputs, for example `nixosConfigurations.<host>`,
  `darwinConfigurations.<host>`, `homeConfigurations.<user>` and free-form
  modules (`nixosModules.*`, `darwinModules.*`, `homeModules.*`). Each output
  lists its settings, and **Edit** and **Delete** controls.
- **Settings:** one per option, each applied to a **Target** output.
  MyNixOS generates the output's Nix file from them.
- **Inputs** (`…/inputs`): the flake's inputs. Their checkboxes pick inputs
  for **Update**, which refreshes their entries in MyNixOS's `flake.lock`.
- **Versions** (`…/versions`): the releases. **Release** publishes the
  current settings as a new numbered version.
- **The newest release:** a tarball holding `flake.nix`, `flake.lock` and
  the generated files, at
  `https://api.mynixos.com/<owner>/<flake>/archive/main.tar.gz`.

A machine builds from that tarball. Either use it directly as the flake
reference, or have a small local flake take it as an input (and pass
`inputs.*.follows` if needed). Every input of the configuration
(nixpkgs, home-manager, and so on) is pinned by MyNixOS's own `flake.lock`,
so an input that's out of date gets updated on the Inputs page, not locally.

Before starting, ask the user for anything you can't find out: the flake's
path, the host name, and how they switch (the command, and whether it needs
their `sudo` password).

## 1. Test the change before touching MyNixOS

Write the new value into a local file first, and evaluate or build it at the
same pinned revisions the release uses:

```bash
src=$(nix flake prefetch --json https://api.mynixos.com/<owner>/<flake>/archive/main.tar.gz | jq -r .storePath)
L=$src/flake.lock
nprev=$(jq -r '.nodes.root.inputs.nixpkgs as $n | .nodes[$n].locked.rev' $L)
hmrev=$(jq -r '.nodes["home-manager"].locked.rev // empty' $L)
```

`$src` also holds the generated Nix files. Read the setting's current value
there, and keep the path: step 3 compares the next release against it.

For a Home Manager setting, a throwaway configuration is enough:

```nix
let
  pkgs = (builtins.getFlake "github:NixOS/nixpkgs/<nprev>").legacyPackages.<system>;
  hm = builtins.getFlake "github:nix-community/home-manager/<hmrev>";
in hm.lib.homeManagerConfiguration {
  inherit pkgs;
  modules = [ ({ config, lib, ... }: {
    home.username = "<user>"; home.homeDirectory = "<home>"; home.stateVersion = "<version>";
    # The option being changed. A MyNixOS setting can use `config`, `lib`
    # and `pkgs`, so import the local file with those in scope:
    # programs.foo.settings = builtins.scopedImport { inherit config lib pkgs; } ./value.nix;
  }) ];
}
```

Build it with
`nix build --impure --no-link --print-out-paths --expr '(import ./test.nix).activationPackage'`
(or `.config.home-files` for the generated files) and inspect the result. Run
the program against the generated config where it can run without a full
session.

Also read the module's source at the pinned revision for defaults that bite.
For example, Home Manager turns each `programs.*.enable<Shell>Integration` on
for every shell by default.

## 2. Edit on MyNixOS

Use Claude in Chrome. Find elements with `find` rather than by screen
coordinates where you can: the window's size changes, and coordinates go
stale. A `find` reference belongs to one page load, so look it up again after
every navigation.

### Kinds of settings

- **Typed settings** live on an option page, such as
  `https://mynixos.com/home-manager/option/<option>` or
  `https://mynixos.com/nix-darwin/option/<option>`. Find the page through
  the site's **Options** search when unsure of the path. The page's editor
  matches the option's type:
  - **Toggle** for booleans.
  - **Nix expression** text box for attribute sets, DAGs, packages and so on.
  - **Plain text** ("strings concatenated by newlines") for `lines` options
    such as `programs.tmux.extraConfig`. It holds the raw text, without Nix
    `''` quotes or indentation.
  - **List editor** for lists of strings: **Add**, then type into the new
    row.
- **Free-form settings** come from **Add setting** under an output on the
  Outputs page. Use them only for options that MyNixOS's catalogue lacks
  (the option page says "Resource not found"). They always show as a Nix
  expression box.

### Saving

- **A new typed setting:** fill in the value, then open the arrow on
  **Apply ▾** and pick the target. Clicking the main part of **Apply**
  without a target saves nothing.
- **An existing setting:** edit it and click its own **Apply**. It keeps its
  target. **Apply** stays greyed out until the form registers a change; a
  click on it while greyed out saves nothing, so check it's enabled first.
- **A toggle:** a new one starts at the option's default. The Apply dropdown
  only opens once the form changes, so to save the value it already shows,
  switch it on and back off.
- **Free-form values must be one line.** The Add setting dialog keeps only
  the first line. A leading comment line then becomes the whole value and
  breaks the generated Nix.
- **Comments:** a typed Nix expression setting keeps comments placed before
  its value, and MyNixOS copies them into the generated file. Notes with no
  natural option can be comments on a setting whose value is the option's
  default.

### Entering text

- `form_input` is fine for short ASCII values.
- For longer text, click into the box, select all with `cmd+a` (`ctrl+a`
  elsewhere), and type or paste the new value.
- To replace part of a long box without retyping it all:
  1. Click inside the box by coordinate (a click by `find` reference can
     leave it unfocused).
  2. With JavaScript, check that `document.activeElement` is the box, then
     select the old text with `setSelectionRange`. This only moves the
     selection; it doesn't change the page.
  3. Type the replacement.
- **Typing or pasting right after a page load is often lost.** Read the value
  back every time and compare its length with what you meant to enter;
  repeat until it matches.
- Text the agent can't type (for example Nerd Font private-use characters):
  write it into a file with a script, inserting each character by code point
  (`chr(0xF1A0)` in Python), copy it with `pbcopy < file`, and paste it.
  Copy it again right before pasting, since the user may have copied
  something in between.
- Typing while nothing is focused sends keys to the page, and a space
  scrolls it. Check the focus before typing.

### Reading the page

- JavaScript that only reads the page (values, lengths, whether text is
  present) is the fastest check. Some agent setups block JavaScript that
  changes page content, and results containing `=`, `?` or `&`, which look
  like query strings. Return counts and booleans, or replace those
  characters before returning.
- After each save, reload the page and confirm that the box holds the new
  value (its length, and the count of any special characters) and that a
  **Target** line is shown.

### Inputs and outputs

- **Deleting an output:** the output's **Delete** control opens a
  confirmation dialog inside the page; confirm it there.
- **Deleting an input** has failed with "Unknown error" before, the input
  coming back on reload. Retry once at most, then leave it and tell the user.
- MyNixOS sometimes adds inputs of its own (such as a second `home-manager`).
  Unused inputs don't change the build.

## 3. Release

1. On `https://mynixos.com/<owner>/<flake>/versions`, click **Release**. An
   **Actions** row reading **Release · Running** (or **Waiting**) confirms it
   started; without that row, the click missed, so click again.
2. Poll the tarball until it changes, then compare it with the previous
   release:

   ```bash
   old=<store path of the previous release, from step 1>
   for i in $(seq 1 40); do
     src=$(nix flake prefetch --refresh --json https://api.mynixos.com/<owner>/<flake>/archive/main.tar.gz | jq -r .storePath)
     [ -n "$src" ] && [ "$src" != "$old" ] && break; sleep 15
   done
   diff -r -x flake.lock "$old" "$src"
   cmp -s "$old/flake.lock" "$src/flake.lock" && echo "lock unchanged"
   ```

   Expect only the intended change. When MyNixOS reorders a file, compare
   sorted lines with indentation stripped instead:
   `diff <(sed 's/^ *//' old.nix | sort) <(sed 's/^ *//' new.nix | sort)`.
   Check `nix-instantiate --parse` on each changed file.

## 4. Build and verify

Build the release without activating it, from the flake that takes the
tarball (run `nix flake update` there first if it pins the tarball in its
own lock):

```bash
darwin-rebuild build --flake '<flake-ref>#<host>'   # nix-darwin
nixos-rebuild build --flake '<flake-ref>#<host>'    # NixOS
readlink -f result; readlink -f /run/current-system
nix store diff-closures /run/current-system ./result
```

- The same path for `result` and `/run/current-system` means the release
  changes nothing at runtime (comments, for example), so no switch is needed.
- `nix store diff-closures` lists package changes; expect none beyond the
  change itself.
- Check the generated files in `result` against what step 1 tested, for
  example the Home Manager files
  (`nix-store -qR result | grep 'home-manager-files$'`), the activation
  script (`result/activate`), or a Brewfile.

## 5. Switch

Switch only when the user asked for it or approved it for this change.
Switching usually needs the user's `sudo` password, so start it where they can
type, such as a new terminal or tmux window, and wait for it to finish:

```bash
S=<scratch directory>; rm -f "$S/switch.exit"
tmux new-window -n switch \
  "bash -c 'script -q $S/switch.log <switch command>; echo \$? > $S/switch.exit; echo Done, press Enter.; read'"
until [ -f "$S/switch.exit" ]; do sleep 5; done
```

Then:

- Read the exit code and the end of the log, with ANSI codes stripped.
- Confirm that `/run/current-system` now points at the built `result`. A
  failed activation leaves it on the old system.
- Close the window you opened.
- Check the change on the running system. Programs that read their
  configuration only at start need a reload. For example, every running tmux
  server has to run `source-file` on its config.

## Rules

- A MyNixOS flake can be public. Never put secrets in a setting; keep them in
  a local file that the configuration reads at run time.
- Pushing to a repository, posting anything public, and switching all need
  the user's go-ahead.
- Changes made outside Nix (`defaults write`, fish universal variables,
  service state) aren't tracked by MyNixOS. Say so when you make one, and
  back up what it replaces.
