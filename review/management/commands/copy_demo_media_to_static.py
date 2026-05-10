from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Copy committed demo media assets (branding + school logos) into STATIC_ROOT/media. "
        "Useful for deployments that serve demo ImageField URLs via WhiteNoise."
    )

    def handle(self, *args, **options):
        src_root = Path(settings.MEDIA_ROOT)
        static_root = Path(settings.STATIC_ROOT)
        dest_root = static_root / "media"

        copied_files = 0
        skipped_missing = 0

        for subdir in ("branding", "school_logos"):
            src_dir = src_root / subdir
            dest_dir = dest_root / subdir

            if not src_dir.exists():
                skipped_missing += 1
                continue

            for src_path in src_dir.rglob("*"):
                if not src_path.is_file():
                    continue

                rel = src_path.relative_to(src_root)
                dest_path = dest_root / rel
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_path, dest_path)
                copied_files += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Copied {copied_files} demo media files into {dest_root}. "
                f"Missing source dirs: {skipped_missing}."
            )
        )
