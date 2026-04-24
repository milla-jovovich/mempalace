# MemPalace Init

Guide the user through a complete MemPalace setup. Follow each step in order,
stopping to report errors and attempt remediation before proceeding.

## Step 1: Check Python version

Run `python3 --version` (or `python --version` on Windows) and confirm the
version is 3.9 or higher. If Python is not found or the version is too old,
tell the user they need Python 3.9+ installed and stop.

## Step 2: Check if mempalace is already installed

Run `pip show mempalace` to see if the package is already present. If it is,
report the installed version and skip to Step 4.

## Step 3: Install mempalace

Run `pip install mempalace`.

### Error handling -- pip failures

If `pip install mempalace` fails, try these fallbacks in order:

1. Try `pip3 install mempalace`
2. Try `python -m pip install mempalace` (or `python3 -m pip install mempalace`)
3. If the error mentions missing build tools or compilation failures (commonly
   from chromadb or its native dependencies):
   - On Linux/macOS: suggest `sudo apt-get install build-essential python3-dev`
     (Debian/Ubuntu) or `xcode-select --install` (macOS)
   - On Windows: suggest installing Microsoft C++ Build Tools from
     https://visualstudio.microsoft.com/visual-cpp-build-tools/
   - Then retry the install command
4. If all attempts fail, report the error clearly and stop.

## Step 4: Ask for project directory

Ask the user which project directory they want to initialize with MemPalace.
Offer the current working directory as the default. Wait for their response
before continuing.

## Step 5: Initialize the palace

Run `mempalace init --yes <dir>` where `<dir>` is the directory from Step 4.

If this fails, report the error and stop.

## Step 6: Configure MCP server

Run the following command to register the MemPalace MCP server with Claude:

    claude mcp add mempalace -- mempalace-mcp

If this fails, report the error but continue to the next step (MCP
configuration can be done manually later).

## Step 7: Verify installation

Run `mempalace status` and confirm the output shows a healthy palace.

If the command fails or reports errors, walk the user through troubleshooting
based on the output.

## Step 8: Show next steps

Tell the user setup is complete and suggest these next actions:

- Use /mempalace:mine to start adding data to their palace
- Use /mempalace:search to query their palace and retrieve stored knowledge
