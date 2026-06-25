# Sentinel Simulation Engine first-run installer design

Date: 2026-06-25

## Goal

Windows beta testers should install Sentinel Simulation Engine from `SentinelSimulationEngine-Setup-<version>.exe`, double-click the installed shortcut, and have missing runtime dependencies handled automatically on first launch.

## Design

- Keep the existing source launcher for development.
- Add an installed-package branch to `Launch-Sentinel-Simulation-Engine.ps1` when `SentinelSimulationEngine.exe` exists beside the launcher.
- The installed launcher checks/downloads the Microsoft Visual C++ Runtime, starts the packaged FastAPI app, waits for `/api/health`, verifies the bundled control panel, and opens the local dashboard.
- The Windows workflow builds the Vite control panel, packages the Python backend with PyInstaller, copies `dist/` beside the executable, and creates `SentinelSimulationEngine-Setup-<version>.exe` with Inno Setup.

## Non-goals

- No live broker integration; Simulation Engine remains a local testing and recorder tool.
- No Node.js runtime in the installed app; the built frontend is static.
- No macOS installer redesign.
