"""Static checks for Windows first-run installer support."""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER_BAT = ROOT / "Launch-Sentinel-Simulation-Engine.bat"
LAUNCHER_PS1 = ROOT / "Launch-Sentinel-Simulation-Engine.ps1"
BUILD_WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"
README = ROOT / "README.md"
WINDOWS_ENTRYPOINT = ROOT / "windows_entrypoint.py"


class WindowsInstallerBootstrapStaticTests(unittest.TestCase):
    def test_launcher_supports_installed_and_source_modes(self):
        batch = LAUNCHER_BAT.read_text(encoding="utf-8")
        script = LAUNCHER_PS1.read_text(encoding="utf-8")

        self.assertIn("Launch-Sentinel-Simulation-Engine.ps1", batch)
        self.assertIn("SentinelSimulationEngine-Setup", batch)
        self.assertIn("if not exist", batch.lower())
        self.assertIn("%*", batch)
        self.assertIn("Sentinel Simulation Engine - Installed App", script)
        self.assertIn("SentinelSimulationEngine.exe", script)
        self.assertIn("Start-InstalledSimulationEngine", script)
        self.assertIn("Start-SourceSimulationEngine", script)
        self.assertIn("Ensure-InstalledRuntimeDependencies", script)
        self.assertIn("Test-VcRuntimeInstalled", script)
        self.assertIn("vc_redist.x64.exe", script)
        self.assertIn("/api/health", script)

    def test_packaged_entrypoint_uses_env_host_and_port(self):
        entrypoint = WINDOWS_ENTRYPOINT.read_text(encoding="utf-8")

        self.assertIn("simulation_engine.main", entrypoint)
        self.assertIn("HOST", entrypoint)
        self.assertIn("PORT", entrypoint)
        self.assertIn("uvicorn.run", entrypoint)

    def test_build_workflow_creates_installer(self):
        workflow = BUILD_WORKFLOW.read_text(encoding="utf-8")

        self.assertIn("Build Sentinel Simulation Engine Windows Installer", workflow)
        self.assertIn("npm run build", workflow)
        self.assertIn("python -m PyInstaller", workflow)
        self.assertIn("windows_entrypoint.py", workflow)
        self.assertIn("SentinelSimulationEngine.exe", workflow)
        self.assertIn("Launch-Sentinel-Simulation-Engine.bat", workflow)
        self.assertIn("Launch-Sentinel-Simulation-Engine.ps1", workflow)
        self.assertIn("SentinelSimulationEngine-Setup-{#MyAppVersion}", workflow)
        self.assertIn('Filename: "{app}\\Launch-Sentinel-Simulation-Engine.bat"', workflow)
        self.assertIn("Minionguyjpro/Inno-Setup-Action", workflow)
        self.assertIn('Move-Item dist frontend-dist', workflow)
        self.assertIn('Copy-Item "frontend-dist" -Destination "$package\\dist"', workflow)

    def test_readme_documents_beta_installer_first_run_behavior(self):
        readme = README.read_text(encoding="utf-8")

        self.assertIn("SentinelSimulationEngine-Setup-<version>.exe", readme)
        self.assertIn("downloads missing runtime dependencies on first launch", readme)
        self.assertIn("Visual C++ Runtime", readme)
        self.assertIn("Sentinel-Simulation-Engine.log", readme)
        self.assertIn("Python, Node.js, npm, or Vite", readme)


if __name__ == "__main__":
    unittest.main()
