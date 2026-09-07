#!/usr/bin/env python3
"""Build dependency-complete Python artifacts for every service into dist/ (D4).

For each services/<svc>/ that has requirements.txt, vendor deps + source into a
zip under dist/. Customer install then uses these prebuilt artifacts (no language
toolchain required); building from source remains optional.
"""
from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DIST = REPO / "dist"


def package_service(svc_dir: Path) -> Path | None:
    src = svc_dir / "src"
    if not src.exists():
        return None
    build_dir = svc_dir / "build"
    build_dir.mkdir(exist_ok=True)
    req = svc_dir / "requirements.txt"
    if req.exists():
        # List form (argv), NOT a shell string: shell=False is the default, so
        # there is no shell to expand globs, interpret metacharacters, or run a
        # second command. Every argument is either a constant or a
        # repo-controlled path (sys.executable, this service's requirements.txt
        # and build dir) — none is externally controlled, so this is not a
        # command-injection sink. The Semgrep audit rule flags any non-literal
        # argv regardless, and shlex.quote does not apply to argv lists, so it is
        # suppressed at the source with a justification. `# nosec B603` covers
        # bandit's equivalent audit finding for the same line.
        subprocess.run(  # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit  # nosec B603
            [sys.executable, "-m", "pip", "install", "-r", str(req), "-t", str(build_dir)],
            check=True,
        )
    # Copy source over vendored deps using Python stdlib — no shell involved.
    import shutil
    for item in src.iterdir():
        dest = build_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)

    DIST.mkdir(exist_ok=True)
    artifact = DIST / f"{svc_dir.name}.zip"
    # Build the zip in-process with zipfile — no bash, no shell injection risk.
    with zipfile.ZipFile(artifact, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in build_dir.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(build_dir))
    return artifact


def main() -> int:
    services = REPO / "services"
    if not services.exists():
        print("No services/ yet.")
        return 0
    built = []
    for svc_dir in sorted(p for p in services.iterdir() if p.is_dir()):
        art = package_service(svc_dir)
        if art:
            built.append(art)
            print(f"packaged {svc_dir.name} -> {art}")
    print(f"Built {len(built)} artifact(s) into dist/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
