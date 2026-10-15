{
  description = "mynixos-skills: Coding-agent skills for MyNixOS (mynixos.com) as a Nix flake";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    systems.url = "github:nix-systems/default";
    flake-parts = {
      url = "github:hercules-ci/flake-parts";
      inputs.nixpkgs-lib.follows = "nixpkgs";
    };
    # Declared explicitly even though `agent-skill-flake` already pulls in
    # `treefmt-nix` transitively: this flake owns its formatter toolchain. The
    # input below `follows` it so the whole tree resolves to one version.
    treefmt-nix = {
      url = "github:numtide/treefmt-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    # The builder library, not a skill: it turns skill directories into
    # installable flakes, aggregates them, and exports the
    # `flakeModules.devshellSkills` module for the dev shell. It carries no
    # skill inputs; the dev shell's skills live in the `skills-devshell/`
    # sub-flake and are invoked at runtime.
    agent-skill-flake = {
      url = "github:nhooey/agent-skill-flake";
      inputs = {
        nixpkgs.follows = "nixpkgs";
        treefmt-nix.follows = "treefmt-nix";
      };
    };
  };

  outputs =
    {
      nixpkgs,
      flake-parts,
      agent-skill-flake,
      ...
    }@inputs:
    let
      # Every skill under ./skills as a package, plus the aggregate and the
      # install/preview apps.
      base = agent-skill-flake.lib.mkAllSkillsFlake {
        inherit nixpkgs;
        source = import ./source.nix;
        skillsDir = ./skills;
        packagePrefix = "agent-skill-";
        # Ship the reference pages a SKILL.md links beside it. Lower-case
        # names only, so a skill's README.md stays in the repo.
        extraFiles = [ "[a-z]*.md" ];
        # Owner+topic, so the aggregate's key can't collide with other repos
        # merged into skillspkgs / nur-packages.
        name = "agent-skills-nhooey-mynixos-all";
      };
    in
    flake-parts.lib.mkFlake { inherit inputs; } {
      systems = import inputs.systems;
      imports = [
        inputs.agent-skill-flake.flakeModules.devshellSkills
        inputs.treefmt-nix.flakeModule
      ];

      agent-skill-flake.devshellSkills = {
        name = "mynixos-skills";
        motd = ''
          {bold}{14}🚀 Entering mynixos-skills dev shell{reset}
          Run {bold}menu{reset} to list available commands.
        '';
      };
      perSystem =
        { system, ... }:
        {
          packages = base.packages.${system};

          apps = base.apps.${system};

          # `nix fmt` runs nixfmt over `.nix` and prettier over `.md` / `.yaml`;
          # `nix flake check` fails on any unformatted file.
          treefmt = {
            projectRootFile = "flake.nix";
            programs.nixfmt.enable = true;
            programs.prettier.enable = true;
            settings.formatter.prettier.includes = [
              "*.md"
              "*.yaml"
              "*.yml"
            ];
          };
        };
    };
}
