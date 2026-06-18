{
  description = "Meshtastic Hermes Agent plugin";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
      in {
        devShells.default = pkgs.mkShell {
          name = "meshtastic-hermes";

          # Use pkgs.python3 (nixpkgs default, currently 3.12+). pip and
          # virtualenv come from the venv itself, not from nixpkgs packages.
          packages = [
            (pkgs.python3.withPackages (ps: [ ps.pip ]))
            pkgs.just
            pkgs.git
          ];

          shellHook = ''
            # Create venv on first entry.
            if [ ! -d .venv ]; then
              echo "[meshtastic-hermes-plugin] Creating Python virtual environment..."
              python3 -m venv .venv
            fi

            # Activate venv (makes python/pip/pytest available without prefix).
            source .venv/bin/activate

            # Install/sync package if not already installed.
            if ! python3 -c "import meshtastic_hermes" 2>/dev/null; then
              echo "[meshtastic-hermes-plugin] Installing package in editable mode..."
              pip install -e ".[dev]" -q
            fi

            echo "[meshtastic-hermes-plugin] Dev shell ready. Run 'just' to see available commands."
          '';
        };
      });
}
