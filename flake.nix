{
  description = "Shared launcher and agent tools for Claude Code and Codex";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/7c8764b7c7b09b34f632464276218ef9090eaa11";
    nixpkgs-claude.url = "github:NixOS/nixpkgs/7fd4004d0511991fff3a0524856a9be09e28c5f0";
    nixpkgs-codex.url = "github:NixOS/nixpkgs/8edc0c72e3a38faf5434e40d1f19431125fe4b30";
  };

  outputs = inputs@{ self, nixpkgs, nixpkgs-claude, nixpkgs-codex, ... }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
      packagesFor = system:
        let
          pkgs = import nixpkgs {
            inherit system;
            config.allowUnfree = true;
          };
          claudePkgs = import nixpkgs-claude {
            inherit system;
            config.allowUnfree = true;
          };
          codexPkgs = import nixpkgs-codex {
            inherit system;
            config.allowUnfree = true;
          };
          codexSource = codexPkgs.fetchFromGitHub {
            owner = "openai";
            repo = "codex";
            tag = "rust-v0.162.1";
            hash = "sha256-vYVQoXQdaK0bejUzcpf9uVrzNWWWAct9AsO/t261FAs=";
          };
          codex = codexPkgs.codex.overrideAttrs (_old: {
            version = "0.162.1";
            src = codexSource;
            cargoDeps = codexPkgs.rustPlatform.fetchCargoVendor {
              pname = "codex";
              version = "0.162.1";
              src = codexSource;
              sourceRoot = "${codexSource.name}/codex-rs";
              hash = "sha256-UTu+ws1DqL375C+1jaVI9HBqDHnTuAQr7/h1rSzsEzg=";
            };
          });
          runtimeInputs = [
            pkgs.bash
            pkgs.coreutils
            pkgs.git
            pkgs.jq
            pkgs.python3
            pkgs.kitty
            claudePkgs.claude-code
            codex
          ];
          crew = pkgs.stdenvNoCC.mkDerivation {
            pname = "crew";
            version = "1.0.0";
            src = self;
            nativeBuildInputs = [ pkgs.makeWrapper ];
            dontBuild = true;
            installPhase = ''
              runHook preInstall
              mkdir -p "$out/bin" "$out/libexec" "$out/share/crew"
              cp bin/crew "$out/libexec/crew"
              cp bin/crew-nodes "$out/libexec/crew-nodes"
              cp -R core "$out/share/crew/core"
              cp -R skills "$out/share/crew/skills"
              cp -R claude/. "$out/share/crew/claude-plugin/"
              mkdir -p "$out/share/crew/claude-plugin/skills"
              cp -R skills/. "$out/share/crew/claude-plugin/skills/"
              makeWrapper "$out/libexec/crew" "$out/bin/crew" \
                --prefix PATH : "${pkgs.lib.makeBinPath runtimeInputs}" \
                --set CREW_BIN "$out/bin/crew" \
                --set CREW_CORE_INSTRUCTIONS \
                "$out/share/crew/core/instructions.md" \
                --set CREW_SKILLS "$out/share/crew/skills" \
                --set CREW_PLUGIN "$out/share/crew/claude-plugin"
              makeWrapper "$out/libexec/crew-nodes" "$out/bin/crew-nodes" \
                --prefix PATH : "${pkgs.lib.makeBinPath runtimeInputs}" \
                --set CREW_NODES_SCRIPT \
                "$out/share/crew/skills/nodes/scripts/nodes.sh"
              runHook postInstall
            '';
          };
          launcherCheck = pkgs.runCommand "crew-launcher-check" {
            nativeBuildInputs = [
              pkgs.bash
              pkgs.git
              pkgs.jq
              pkgs.python3
              pkgs.shellcheck
            ];
          } ''
            mkdir -p source
            cp -R ${self}/. source/
            chmod -R u+w source
            cd source
            export PYTHONDONTWRITEBYTECODE=1
            python3 -m unittest discover \
              -s tests -p '*_test.py' -v
            mapfile -t shell_scripts < <(
              find skills -type f -path '*/scripts/*.sh' \
                -print 2>/dev/null
            )
            shellcheck bin/crew bin/crew-nodes "''${shell_scripts[@]}"
            touch "$out"
          '';
        in
        {
          packages.default = crew;
          packages.crew = crew;
          checks.launcher = launcherCheck;
        };
    in
    {
      packages = forAllSystems (system: (packagesFor system).packages);
      checks = forAllSystems (system: (packagesFor system).checks);
    };
}
