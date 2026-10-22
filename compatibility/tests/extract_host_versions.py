"""Extract real PE VERSIONINFO for the optional Linux transaction harness."""
import argparse
import json
from pathlib import Path

import pefile


def versions(root):
    result = {}
    for name in ("cascadeur.exe", "python311.dll", "Qt6Core.dll", "Qt6Gui.dll",
                 "Qt6Qml.dll", "Qt6Network.dll", "Qt6Quick.dll"):
        pe = pefile.PE(str(root / name))
        fixed = pe.VS_FIXEDFILEINFO[0]
        strings = {}
        for group in getattr(pe, "FileInfo", []):
            for entry in group:
                for table in getattr(entry, "StringTable", []):
                    strings.update({k.decode(): v.decode() for k, v in table.entries.items()})
        result[name] = {"FileMajorPart": fixed.FileVersionMS >> 16,
                        "FileMinorPart": fixed.FileVersionMS & 65535,
                        "FileBuildPart": fixed.FileVersionLS >> 16,
                        "FileVersion": strings.get("FileVersion", "")}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy", type=Path, required=True)
    parser.add_argument("--modern", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps({"legacy": versions(args.legacy),
                                      "modern": versions(args.modern) if args.modern else {}},
                                     indent=2), encoding="utf-8")
