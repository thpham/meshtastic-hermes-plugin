# Meshtastic Hermes plugin — task runner.
# Run `just` (or `just --list`) to see available recipes.

# Where Hermes discovers user plugins.
hermes_plugins := env("HERMES_PLUGINS_DIR", env("HOME") + "/.hermes/plugins")
plugin_name := "meshtastic"
pkg_dir := justfile_directory() + "/meshtastic_hermes"

# Show available recipes.
default:
    @just --list

# Install the package (editable) with the dev extras. `meshtastic` comes in as a
# hard dependency automatically.
install:
    pip install -e ".[dev]"

# Symlink the package into ~/.hermes/plugins/meshtastic for local development.
link:
    mkdir -p "{{hermes_plugins}}"
    ln -sfn "{{pkg_dir}}" "{{hermes_plugins}}/{{plugin_name}}"
    @echo "Linked {{pkg_dir}} -> {{hermes_plugins}}/{{plugin_name}}"

# Remove the development symlink.
unlink:
    rm -f "{{hermes_plugins}}/{{plugin_name}}"
    @echo "Unlinked {{hermes_plugins}}/{{plugin_name}}"

# Add the plugin to the Hermes enabled allow-list.
enable:
    hermes plugins enable {{plugin_name}}

# Disable the plugin.
disable:
    hermes plugins disable {{plugin_name}}

# Verbose plugin discovery to debug loading.
hermes-debug:
    HERMES_PLUGINS_DEBUG=1 hermes plugins list

# Run the test suite (no radio required).
test:
    pytest -q

# Lint with ruff.
lint:
    ruff check .

# Auto-format with ruff.
fmt:
    ruff format .

# Quick import sanity check.
check:
    python -c "import meshtastic_hermes; print('meshtastic_hermes', meshtastic_hermes.__version__)"

# Standalone harness — run the plugin without Hermes. Examples:
#   just standalone list
#   just standalone call meshtastic_kb_summary
#   just standalone observe 192.168.1.50 30
standalone *ARGS:
    python -m meshtastic_hermes {{ARGS}}
