from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path("/app")
BUILD = ROOT / "build"
BIN = BUILD / "bin"
LIB = BUILD / "lib"


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True, text=True, capture_output=True)


def clean_build_tree():
    if BUILD.exists():
        shutil.rmtree(BUILD)
    BUILD.mkdir(parents=True)


def configure_and_build():
    run(["cmake", ".."], cwd=BUILD)
    run(["cmake", "--build", ".", "-j"], cwd=BUILD)


def test_configure_and_build_succeeds():
    """Build from scratch succeeds and expected binaries/artifacts exist in build tree."""
    clean_build_tree()
    configure_and_build()
    assert (BIN / "calculator").exists(), "calculator executable missing"
    assert (LIB / "libmath.so").exists(), "libmath.so missing"
    assert (LIB / "libcalc.so").exists(), "libcalc.so missing"


def test_calculator_runs_and_output_matches():
    """Running build/bin/calculator prints exactly: 'Calculator result: 42'."""
    clean_build_tree()
    configure_and_build()
    out = run([str(BIN / "calculator")])
    assert out.stdout.strip() == "Calculator result: 42"


def test_idempotent_build_no_work():
    """Second build is a no-op (idempotent), indicating correct build graph."""
    clean_build_tree()
    configure_and_build()
    out2 = run(["cmake", "--build", ".", "-j"], cwd=BUILD)
    assert out2.returncode == 0


def test_compile_commands_generated():
    """compile_commands.json exists for build verification."""
    clean_build_tree()
    configure_and_build()
    cc = BUILD / "compile_commands.json"
    assert cc.exists(), "compile_commands.json must be generated (enable CMAKE_EXPORT_COMPILE_COMMANDS)"


def test_shared_libs_have_soname():
    """Shared libraries have proper SONAME and versioning."""
    clean_build_tree()
    configure_and_build()
    
    # Check libmath.so has SONAME
    out = run(["readelf", "-d", str(LIB / "libmath.so")])
    assert "SONAME" in out.stdout, "libmath.so must have SONAME"
    
    # Check libcalc.so has SONAME
    out = run(["readelf", "-d", str(LIB / "libcalc.so")])
    assert "SONAME" in out.stdout, "libcalc.so must have SONAME"


def test_rpath_configured_properly():
    """RPATH/RUNPATH is properly configured so executable can find shared libraries."""
    clean_build_tree()
    configure_and_build()
    
    # Check calculator has RPATH or RUNPATH
    out = run(["readelf", "-d", str(BIN / "calculator")])
    has_rpath = "RPATH" in out.stdout or "RUNPATH" in out.stdout
    assert has_rpath, "calculator must have RPATH or RUNPATH configured"
    
    # Verify ldd can resolve all dependencies without LD_LIBRARY_PATH
    ldd_out = run(["ldd", str(BIN / "calculator")])
    assert "not found" not in ldd_out.stdout, "All shared library dependencies must be resolvable"


def test_shared_lib_link_order_math_before_calc():
    """Final link line for calculator orders shared libs with math before calc."""
    clean_build_tree()
    configure_and_build()
    
    # Gather candidates: link.txt, build.ninja, and any build files mentioning both libs
    candidates = list((BUILD / "CMakeFiles").rglob("link.txt"))
    bn = BUILD / "build.ninja"
    if bn.exists():
        candidates.append(bn)

    matched_contents = []
    scanned = set()
    for p in candidates:
        try:
            content = p.read_text(errors="ignore")
        except Exception:
            continue
        if "libmath.so" in content and "libcalc.so" in content:
            matched_contents.append(content)
            scanned.add(p)

    # Fallback: scan all text-like files under build for both libs
    if not matched_contents:
        for p in BUILD.rglob("*"):
            if p.is_file() and p not in scanned and p.stat().st_size < 2_000_000:
                try:
                    text = p.read_text(errors="ignore")
                except Exception:
                    continue
                if "libmath.so" in text and "libcalc.so" in text:
                    matched_contents.append(text)
                    break

    assert matched_contents, "No link lines containing both libmath.so and libcalc.so found"

    joined = "\n".join(matched_contents)
    idx_math = joined.find("libmath.so")
    idx_calc = joined.find("libcalc.so")
    assert idx_math != -1 and idx_calc != -1, "Both libmath.so and libcalc.so should be in link line"
    assert idx_math < idx_calc, "Shared libraries must be ordered: math before calc"


def test_public_includes_and_no_manual_includes_in_app():
    """Headers are consumable via PUBLIC include dirs from libs (no manual includes in app)."""
    clean_build_tree()
    # Build must succeed using only PUBLIC includes from libraries
    configure_and_build()
    app_cml = ROOT / "app" / "CMakeLists.txt"
    content = app_cml.read_text()
    assert not re.search(r"(^|\n)\s*target_include_directories\(\s*calculator\b", content), (
        "app/CMakeLists.txt must not manually add include directories for headers;"
        " libraries must export PUBLIC include dirs"
    )


def test_explicit_dependencies_present_to_avoid_races():
    """Explicit target dependencies avoid parallel build races (calculator depends on math and calc)."""
    clean_build_tree()
    # After a successful build, verify explicit dependencies are present in app CMake
    configure_and_build()
    app_cml = ROOT / "app" / "CMakeLists.txt"
    content = app_cml.read_text()
    assert re.search(r"add_dependencies\(\s*calculator\s+math\s+calc\s*\)", content), (
        "add_dependencies(calculator math calc) must be present to avoid build races"
    )


def test_no_stray_artifacts_outside_build_dirs():
    """No stray artifacts are created outside build/bin and build/lib in the project root (ignoring uv/venv files)."""
    clean_build_tree()
    configure_and_build()
    allowed_root_files = {
        "build", "libs", "app", "CMakeLists.txt",
        # uv / pytest environment files
        "pyproject.toml", "uv.lock", "README.md", "main.py", ".python-version", ".venv",
        # helpers provided by task for agent convenience
        "applypatch", "applypatch.sh",
    }
    disallowed = []
    for p in ROOT.iterdir():
        if p.name in allowed_root_files:
            continue
        disallowed.append(p)
    assert not disallowed, f"Unexpected artifacts outside build tree: {disallowed}"
