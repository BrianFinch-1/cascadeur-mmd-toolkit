"""Build the Windows compatibility ZIP from hash-pinned upstream artifacts.

Usage: python compatibility/build_release.py --cache downloads --output dist
No host Qt DLL, plugin, QML import tree or interpreter is redistributed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

import pefile

HERE = Path(__file__).resolve().parent
SOURCES = [
    ("cascadeur-MMD-toolkit-1.0.zip", "https://github.com/BrianFinch-1/cascadeur-mmd-toolkit/releases/download/v1.0/cascadeur-MMD-toolkit-1.0.zip", "ffd8694ffad2a39399014b41a64201d007a0e4a9592841b229a8c0bd25d42bae"),
    ("PySide6_Essentials-6.5.3-cp37-abi3-win_amd64.whl", "https://files.pythonhosted.org/packages/06/25/24216f5b7cf59bb2a768a63586b4a49553ace48c3e9f18441eff55d2d658/PySide6_Essentials-6.5.3-cp37-abi3-win_amd64.whl", "f928b98ec349c87f9ccc63a482917779f59fa646893722c53c2fe2a1e4f335e0"),
    ("shiboken6-6.5.3-cp37-abi3-win_amd64.whl", "https://files.pythonhosted.org/packages/a1/b1/47d63d65698f047e9c3ab3dfa9a67c3364d73579b2cece0eb82b24b90868/shiboken6-6.5.3-cp37-abi3-win_amd64.whl", "a013367e38a12b3f69ba02e79f133df4fba8d21b55a78c6999cdb31c25609524"),
    ("python-3.11.9-embed-amd64.zip", "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip", "009d6bf7e3b2ddca3d784fa09f90fe54336d5b60f0e0f305c37f400bf83cfd3b"),
]
PYSIDE_FILES = ["__init__.py", "_config.py", "QtCore.pyd", "QtCore.pyi",
                "QtNetwork.pyd", "QtNetwork.pyi", "QtQml.pyd", "QtQml.pyi",
                "pyside6.abi3.dll", "pyside6qml.abi3.dll", "support/__init__.py",
                "support/deprecated.py"]
SHIBOKEN_FILES = ["__init__.py", "_config.py", "Shiboken.pyd", "shiboken6.abi3.dll"]
REF_DLL = "resources/scripts/python/scripts/vmd_bridge/native/qt_list_ref.dll"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def fetch(cache):
    result = {}
    cache.mkdir(parents=True, exist_ok=True)
    for name, url, sha in SOURCES:
        path = cache / name
        if not path.exists():
            temporary = path.with_suffix(path.suffix + ".part")
            urllib.request.urlretrieve(url, temporary)
            if digest(temporary).lower() != sha:
                temporary.unlink()
                raise ValueError("Download hash mismatch: " + name)
            temporary.replace(path)
        if digest(path).lower() != sha:
            raise ValueError("Cached artifact hash mismatch: " + name)
        result[name] = path
    return result


def build(cache, output):
    artifacts = fetch(cache)
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mmd-compat-") as directory:
        work = Path(directory)
        with zipfile.ZipFile(artifacts[SOURCES[0][0]]) as archive:
            archive.extractall(work)
        root = work / "cascadeur MMD toolkit 1.0"
        manifest = json.loads((root / "MANIFEST-SHA256.json").read_text(encoding="utf-8-sig"))
        for entry in manifest["files"]:
            assert digest(root / entry["source"]) == entry["sha256"]
        # Modern dialog source is copied byte-for-byte from the pinned v1.0
        # release. Only the legacy host loads the compatibility implementation.
        original_dialogs = root / "payload/resources/scripts/python/scripts/vmd_bridge/dialogs.py"
        shutil.copy2(original_dialogs, original_dialogs.with_name("_dialogs_modern.py"))
        for required in ("LGPL-3.0.txt", "GPL-3.0.txt", "COMPATIBILITY.txt"):
            if not (HERE / "overlay" / required).is_file():
                raise FileNotFoundError("Missing release notice: " + required)
        shutil.copytree(HERE / "overlay", root, dirs_exist_ok=True)
        payload = root / "payload"
        site = payload / "python/Lib/site-packages"
        for source, package, names in [(SOURCES[1][0], "PySide6", PYSIDE_FILES),
                                       (SOURCES[2][0], "shiboken6", SHIBOKEN_FILES)]:
            with zipfile.ZipFile(artifacts[source]) as archive:
                for name in names:
                    archive.extract(package + "/" + name, site)
        with zipfile.ZipFile(artifacts[SOURCES[3][0]]) as archive:
            archive.extract("python3.dll", payload)
            (root / "PYTHON-LICENSE.txt").write_bytes(archive.read("LICENSE.txt"))
        native = payload / REF_DLL
        native.parent.mkdir(parents=True, exist_ok=True)
        obj = work / "qt_list_ref.obj"
        subprocess.run([sys.executable, "-m", "ziglang", "cc", "-target", "x86_64-windows-msvc",
                        "-c", "-Oz", "-fno-stack-protector", "-fno-sanitize=all",
                        str(HERE / "native/qt_list_ref.c"), "-o", str(obj)], check=True)
        subprocess.run([sys.executable, "-m", "ziglang", "lld-link", "/dll", "/noentry",
                        "/nodefaultlib", "/timestamp:0", "/out:" + str(native), str(obj)], check=True)
        # Linker side products are build artifacts, never installer targets.
        for path in native.parent.iterdir():
            if path != native:
                path.unlink()
        helper = pefile.PE(str(native))
        assert helper.OPTIONAL_HEADER.AddressOfEntryPoint == 0
        assert not hasattr(helper, "DIRECTORY_ENTRY_IMPORT")

        legacy_targets = {"python3.dll", REF_DLL}
        legacy_targets.update("python/Lib/site-packages/PySide6/" + n for n in PYSIDE_FILES)
        legacy_targets.update("python/Lib/site-packages/shiboken6/" + n for n in SHIBOKEN_FILES)
        # Record the actual imports of the three compatible bindings. Installer
        # preflight checks every required host Qt export without executing it.
        native_requirements = {"cascadeur.exe": set(), "python311.dll": {"Py_GetVersion"},
                               "Qt6Gui.dll": {"?allWindows@QGuiApplication@@SA?AV?$QList@PEAVQWindow@@@@XZ"},
                               "Qt6Core.dll": {"?deallocate@QArrayData@@SAXPEAU1@_J1@Z"},
                               "Qt6Quick.dll": set()}
        for target in legacy_targets:
            if not target.endswith((".pyd", ".dll")):
                continue
            pe = pefile.PE(str(payload / target))
            assert pe.FILE_HEADER.Machine == 34404
            for dependency in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
                name = dependency.dll.decode("ascii")
                if name.startswith("Qt6"):
                    native_requirements.setdefault(name, set()).update(
                        symbol.name.decode("ascii") for symbol in dependency.imports)
        manifest["legacy_requirements"] = {
            "machine": 34404,
            "native": [{"path": name, "exports": sorted(symbols)}
                       for name, symbols in sorted(native_requirements.items())],
            "files": ["resources/scripts/python/commands_rule.py",
                      "resources/scripts/python/events_rule.py",
                      "resources/scripts/python/pycsc/__init__.py",
                      "python/Lib/site-packages/numpy/__init__.py"],
            "directories": ["resources/scripts/python/commands", "resources/scripts/python/events"],
        }
        # topLevelWindows() is inline in the vendor Qt build. The native
        # adapter has allWindows() as its exported fallback; require that API.
        for requirement in manifest["requirements"]["native"]:
            if requirement["path"] == "Qt6Gui.dll":
                requirement["exports"] = [name for name in requirement["exports"]
                                          if "topLevelWindows@" not in name]
        manifest["compatibility_revision"] = 1
        manifest["files"] = []
        for path in sorted(payload.rglob("*")):
            if not path.is_file():
                continue
            target = path.relative_to(payload).as_posix()
            profile = "legacy" if target in legacy_targets else "native" if target == "D3D11.dll" else "all"
            manifest["files"].append({"source": "payload/" + target, "target": target,
                                      "sha256": digest(path), "size": path.stat().st_size,
                                      "profile": profile})
        (root / "DEPENDENCY-SOURCES.json").write_text(json.dumps([
            {"name": name, "url": url, "sha256": sha} for name, url, sha in SOURCES
        ], indent=2) + "\n", encoding="utf-8")
        # License texts live in the overlay; source/relinking information is
        # included alongside them. Never redistribute Qt's commercial license.
        manifest["package_files"] = [
            {"path": p.name, "sha256": digest(p), "size": p.stat().st_size}
            for p in sorted(root.iterdir()) if p.is_file() and p.name != "MANIFEST-SHA256.json"]
        (root / "MANIFEST-SHA256.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8-sig")
        final = output / "cascadeur-MMD-toolkit-1.0-2026.1.3-compat.zip"
        with zipfile.ZipFile(final, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    info = zipfile.ZipInfo(path.relative_to(work).as_posix(), (2026, 10, 21, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    archive.writestr(info, path.read_bytes())
        (output / "SHA256SUMS.txt").write_text(digest(final) + "  " + final.name + "\n", encoding="ascii")
        print(final)
        print(digest(final))
        return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=HERE / ".cache")
    parser.add_argument("--output", type=Path, default=HERE / "dist")
    args = parser.parse_args()
    build(args.cache.resolve(), args.output.resolve())
