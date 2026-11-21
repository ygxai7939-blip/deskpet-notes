"""Validate a character ZIP or build one from a manifest and its atlas."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

from pet_packages import SAFE_COMPONENT, read_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Existing ZIP or a folder containing pet.json and its atlas")
    parser.add_argument("output", type=Path, nargs="?", help="Destination ZIP when source is a folder")
    args = parser.parse_args()
    try:
        if args.output is None:
            result = read_package(args.source)
        else:
            manifest = args.source / "pet.json"
            metadata = json.loads(manifest.read_text(encoding="utf-8-sig"))
            atlas = metadata.get("spritesheetPath", "spritesheet.webp")
            if not isinstance(atlas, str) or not SAFE_COMPONENT.fullmatch(atlas):
                raise ValueError("图集文件名必须是单个文件名。")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=args.output.parent) as temporary:
                candidate = Path(temporary) / "candidate.zip"
                with ZipFile(candidate, "w", ZIP_DEFLATED) as archive:
                    archive.write(manifest, "pet.json")
                    archive.write(args.source / atlas, atlas)
                result = read_package(candidate)
                candidate.replace(args.output)
    except (OSError, ValueError, AttributeError) as error:
        parser.exit(1, f"{error}\n")
    print(f"校验通过 · {result.name} ({result.pet_id}) · 待机 {len(result.idle_frames)} 帧")


if __name__ == "__main__":
    main()
