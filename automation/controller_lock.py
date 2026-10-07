"""Exclusive browser controller lease shared across automation directories."""
from contextlib import contextmanager
from pathlib import Path
import os
import tempfile


@contextmanager
def controller_lease(browser='chrome'):
    file=(Path(tempfile.gettempdir())/('tallnum-'+browser+'-controller.lock')).open('a+b')
    file.seek(0);file.write(b'0');file.flush();file.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(file.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError as error:
        file.close()
        raise RuntimeError('Another Tallnum browser controller is active; board retained') from error
    try:yield
    finally:
        file.seek(0)
        if os.name=='nt':msvcrt.locking(file.fileno(),msvcrt.LK_UNLCK,1)
        else:fcntl.flock(file.fileno(),fcntl.LOCK_UN)
        file.close()
