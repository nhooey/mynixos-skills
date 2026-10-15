{
  description = "mynixos-config-change: Coding-agent skill — change a NixOS, nix-darwin or Home Manager configuration on MyNixOS (mynixos.com) through the browser, then release, build, verify and switch";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    agent-skill-flake.url = "github:nhooey/agent-skill-flake";
    agent-skill-flake.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    { nixpkgs, agent-skill-flake, ... }:
    agent-skill-flake.lib.mkSkillFlake {
      inherit nixpkgs;
      source = import ../../source.nix;
      skillName = "mynixos-config-change";
      src = ./.;
    };
}
