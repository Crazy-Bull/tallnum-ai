import errno
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from automation.common import link_or_copy


class StorageTests(unittest.TestCase):
    def test_cross_disk_copy_preserves_bytes_and_source(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'source';target=Path(directory)/'target'
            source.write_bytes(b'template contents')
            with patch('automation.common.os.link',side_effect=OSError(errno.EXDEV,'cross disk')):
                link_or_copy(source,target)
            self.assertEqual(source.read_bytes(),target.read_bytes())

    def test_other_errors_do_not_overwrite_existing_target(self):
        with patch('automation.common.os.link',side_effect=FileExistsError(errno.EEXIST,'exists')):
            with self.assertRaises(FileExistsError):link_or_copy('source','target')


if __name__=='__main__':unittest.main()
