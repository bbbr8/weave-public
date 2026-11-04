import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from reasoning_layer.native import transfer
from reasoning_layer.recovery import resume_staging

class Transport(unittest.TestCase):
    def test_device_path_is_local_not_an_scp_hostname(self):
        with patch('reasoning_layer.native.command') as call:
            transfer('put',r'\\?\C:\long\request.json','/Users/example/request.json',Path('.'),'stage')
        script=call.call_args.args[0]
        self.assertNotIn('\\\\?\\',script);self.assertIn("'C:\\long\\request.json'",script)
    def test_unc_device_prefix_preserves_share(self):
        with patch('reasoning_layer.native.command') as call:
            transfer('get','/Users/example/result.json',r'\\?\UNC\host\share\result.json',Path('.'),'fetch')
        self.assertIn("'\\\\host\\share\\result.json'",call.call_args.args[0])
    def test_recovery_does_not_resubmit_started_execution(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'state.json').write_text(json.dumps(dict(remote='/known/job')));(p/'execute.ps1').write_text('already attempted')
            with patch('reasoning_layer.recovery.command') as call:
                with self.assertRaisesRegex(RuntimeError,'already have started'):resume_staging(p)
                call.assert_not_called()

if __name__=='__main__':unittest.main()
