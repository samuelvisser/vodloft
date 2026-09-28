"""Create digest manifests for trusted Docker-build Source wheelhouses."""
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
for source_id in ("yt-dlp", "dailywire"):
    bundle = root / source_id / "0.1.0"
    wheels = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in sorted(bundle.glob("*.whl"))}
    (bundle / "release.json").write_text(json.dumps({
        "source_id": source_id, "version": "0.1.0", "wheels": wheels}, indent=2))
