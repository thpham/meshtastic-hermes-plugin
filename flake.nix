{
  description = "Meshtastic Hermes Agent plugin";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    let
      # Build the plugin against an arbitrary python package set. Reused by both
      # the per-system `packages` output and the `overlays.default`, so consumers
      # get a derivation built against THEIR python (ABI-matched for the Hermes
      # service).
      mkPlugin = py: py.buildPythonPackage {
        pname = "meshtastic-hermes-plugin";
        version = "0.1.0";
        pyproject = true;
        src = ./.;

        build-system = [ py.setuptools ];

        dependencies = [
          py.meshtastic
          py.pyyaml
        ];

        # nixpkgs may carry a slightly older meshtastic than the PyPI floor
        # (>=2.7.9); the plugin only uses stable APIs, so relax rather than break
        # builds on consumers' pinned nixpkgs.
        pythonRelaxDeps = [ "meshtastic" ];

        nativeCheckInputs = [ py.pytestCheckHook ];
        pythonImportsCheck = [ "meshtastic_hermes" ];

        meta = {
          description = "Hermes Agent plugin to interact with a Meshtastic mesh over TCP/IP";
          homepage = "https://github.com/thpham/meshtastic-hermes-plugin";
        };
      };

      # Consumer-facing overlay: inject the plugin into every python package set
      # (python3Packages, python311Packages, ...). This is what a NixOS user adds
      # so `services.hermes-agent.extraPythonPackages` builds it against the
      # service's python. Deliberately NOT including the Darwin fix below — Linux
      # consumers don't need it, and it keeps their meshtastic on the binary cache.
      overlay = final: prev: {
        pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [
          (pyFinal: pyPrev: {
            meshtastic-hermes-plugin = mkPlugin pyFinal;
          })
        ];
      };

      # Darwin-only meshtastic fix. nixpkgs `meshtastic` references the Linux-only
      # `pytap2` (via its `tunnel` optional-dependency extra, which this plugin
      # never uses), so merely *evaluating* meshtastic is refused on Darwin.
      # meshtastic is also not in the binary cache for Darwin, so it builds from
      # source locally regardless — and its upstream test suite may not pass on
      # macOS. So on Darwin we drop the unused `tunnel` extra (fixes evaluation)
      # and skip meshtastic's own checks (faster, robust one-time local build).
      # Guarded by isDarwin, so on Linux this is a no-op and consumers keep the
      # cached stock meshtastic binary.
      darwinMeshtasticFix = final: prev:
        prev.lib.optionalAttrs prev.stdenv.hostPlatform.isDarwin {
          pythonPackagesExtensions = prev.pythonPackagesExtensions ++ [
            (pyFinal: pyPrev: {
              meshtastic = pyPrev.meshtastic.overridePythonAttrs (old: {
                optional-dependencies =
                  builtins.removeAttrs (old.optional-dependencies or { }) [ "tunnel" ];
                doCheck = false;
              });
            })
          ];
        };
    in
    {
      overlays.default = overlay;
    } // flake-utils.lib.eachDefaultSystem (system:
      let
        # Our own outputs apply the Darwin fix so `nix build` / `nix develop`
        # work on macOS. On Linux the overlay is a harmless no-op.
        pkgs = import nixpkgs {
          inherit system;
          overlays = [ darwinMeshtasticFix ];
        };
        plugin = mkPlugin pkgs.python3Packages;
      in {
        # `nix build` / `inputs.<this>.packages.<system>.default`
        packages.default = plugin;
        packages.meshtastic-hermes-plugin = plugin;

        # Reproducible, pip-free dev shell: every Python dependency comes from
        # nixpkgs (no venv, no `pip install`), and the working tree is on
        # PYTHONPATH so edits are picked up immediately.
        devShells.default = pkgs.mkShell {
          name = "meshtastic-hermes";

          packages = [
            (pkgs.python3.withPackages (ps: [
              ps.meshtastic
              ps.pyyaml
              ps.pytest
            ]))
            pkgs.ruff
            pkgs.just
            pkgs.git
          ];

          shellHook = ''
            # Run the plugin straight from the source tree — fully reproducible.
            export PYTHONPATH="$PWD''${PYTHONPATH:+:$PYTHONPATH}"
            echo "[meshtastic-hermes-plugin] Dev shell ready (python ${pkgs.python3.version}, deps from nixpkgs)."
            echo "[meshtastic-hermes-plugin] Run 'just' to see available commands."
          '';
        };
      });
}
