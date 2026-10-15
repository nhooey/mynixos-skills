{
  description = "mynixos-skills dev-shell skill set — an isolated sub-flake invoked at RUNTIME by the root devShell, never a root input. The skill sources (the git/GitHub pack plus skillspkgs' authoring combination) live only in THIS flake's lock, so the root mynixos-skills stays a leaf with zero skill inputs and transitive consumers never drag the skill mesh in.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    systems.url = "github:nix-systems/default";

    # The builder lib. agent-skill-flake carries zero skill inputs, so it does
    # not drag the skill mesh into this sub-flake's lock — only the skill
    # sources below do.
    agent-skill-flake = {
      url = "github:nhooey/agent-skill-flake";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # Dev-shell skill sources. They follow the parent `nixpkgs` but NOT
    # `agent-skill-flake`: forcing skillspkgs' `authoring` combination's
    # transitive sources onto a single pinned builder surfaces an ownerless
    # aggregate-key the strict namespace check rejects, so each source keeps
    # its own (compatible) builder. `mkDevshellSkillsFlake` still runs from this
    # flake's `agent-skill-flake.lib`, so the combiner is the pinned rev above.

    git-skills = {
      url = "github:nhooey/git-skills";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # skillspkgs' curated `authoring` combination, surfaced through its own
    # subdir flake (`mkCombination` keeps a combination re-composable). A
    # `?dir=` into a *different* repo fetches cleanly for transitive consumers.
    skillspkgs-combinations = {
      url = "github:nhooey/skillspkgs?dir=sources/combinations";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  # One `mkDevshellSkillsFlake` call: the dev shell's whole skill set as a
  # single combination, surfaced as runnable apps (reconcile / purge / …). This
  # reproduces the previously-inlined root set exactly — the git/GitHub pack
  # plus skillspkgs' `authoring` combination.
  outputs =
    {
      nixpkgs,
      agent-skill-flake,
      ...
    }@inputs:
    agent-skill-flake.lib.mkDevshellSkillsFlake {
      inherit nixpkgs;
      systems = import inputs.systems;
      name = "mynixos-skills-devshell";
      # envName and packagePrefix are left at their library defaults:
      # mkDevshellSkillsFlake derives envName = "agent-skills-${name}"
      # (== agent-skills-mynixos-skills-devshell) and packagePrefix
      # defaults to "agent-skill-", so both equal what was spelled out here.
      sources = [
        { source = inputs.git-skills; }
        { source = inputs.skillspkgs-combinations.combinations.authoring; }
      ];
    };
}
