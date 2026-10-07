"""Remove rebuildable solver artifacts only after fixed-policy certification."""
from pathlib import Path
from .library import load_catalog


def prune_completed(directory):
    directory=Path(directory).resolve()
    sources={Path(p['source']).resolve() for p in load_catalog(directory)['policies']}
    certified={Path(p['source']).resolve() for p in load_catalog(directory,certified_only=True)['policies']}
    freed=0
    for source in certified:
        work=source.parent
        if not any(work.is_relative_to(directory/name) for name in ('aggressive','certification')) or not (work/'exit_probability_02.result.json').exists():continue
        for pattern in ('*.values.bin','0[1-6]*.policy.bin'):
            for file in work.glob(pattern):
                if file.resolve() in sources:continue
                freed+=file.stat().st_size
                file.unlink()
                for marker in work.glob(file.name.split('.')[0]+'.complete.json'):marker.unlink()
    return freed
